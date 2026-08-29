import { FirebaseApp, initializeApp, getApps } from "firebase/app";
import {
  Auth,
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signOut as firebaseSignOut,
  onAuthStateChanged,
  User
} from "firebase/auth";
import { Firestore, getFirestore } from "firebase/firestore";
import { FirebaseStorage, getStorage } from "firebase/storage";

// Approved guest emails (external collaborators granted dashboard access)
const GUEST_EMAILS: string[] = [
  "elisa.belaz@un.org",
];

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY || '',
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || '',
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || '',
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET || '',
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID || '',
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID || ''
};

let app: FirebaseApp | null = null;
let auth: Auth | null = null;
let db: Firestore | null = null;
let storage: FirebaseStorage | null = null;
let googleProvider: GoogleAuthProvider | null = null;

// Initialize Firebase - only run in browser and only once
export function initializeFirebase() {
  if (typeof window === 'undefined') return null;
  
  if (!app && getApps().length === 0) {
    try {
      app = initializeApp(firebaseConfig);
      auth = getAuth(app);
      db = getFirestore(app);
      storage = getStorage(app);
      
      // Configure Google Auth Provider
      googleProvider = new GoogleAuthProvider();
      googleProvider.setCustomParameters({
        prompt: "select_account",
      });
    } catch (error) {
      console.error('Firebase initialization error:', error);
    }
  }
  
  return { app, auth, db, storage, googleProvider };
}

// Export getters that initialize on demand
export const getFirebaseAuth = () => {
  const firebase = initializeFirebase();
  return firebase?.auth || null;
};

export const getFirebaseDb = () => {
  const firebase = initializeFirebase();
  return firebase?.db || null;
};

export const getFirebaseStorage = () => {
  const firebase = initializeFirebase();
  return firebase?.storage || null;
};

/**
 * Sign in with Google and enforce @pakairquality.com domain restriction
 */
export async function signInWithGoogle(): Promise<User> {
  const firebase = initializeFirebase();
  if (!firebase || !firebase.auth || !firebase.googleProvider) {
    throw new Error("Firebase not initialized");
  }

  try {
    const result = await signInWithPopup(firebase.auth, firebase.googleProvider);
    const user = result.user;
    const email = user.email?.toLowerCase() || "";

    // Enforce access control: team domain + approved guests
    const isTeamMember =
      user.emailVerified && email.endsWith("@pakairquality.com");
    const isGuest =
      user.emailVerified && GUEST_EMAILS.includes(email);

    if (!isTeamMember && !isGuest) {
      await firebaseSignOut(firebase.auth);
      throw new Error("Access restricted. Contact the team for an invitation.");
    }

    return user;
  } catch (error) {
    console.error("Sign in error:", error);
    throw error;
  }
}

/**
 * Sign out the current user
 */
export async function signOut(): Promise<void> {
  const authInstance = getFirebaseAuth();
  if (authInstance) {
    await firebaseSignOut(authInstance);
  }
}

/**
 * Check if the current user has a valid domain
 */
export function isValidUser(user: User | null): boolean {
  if (!user || !user.email) return false;
  const email = user.email.toLowerCase();

  return user.emailVerified && (
    email.endsWith("@pakairquality.com") ||
    GUEST_EMAILS.includes(email)
  );
}

/**
 * Listen to auth state changes
 */
export function onAuthStateChange(callback: (user: User | null) => void): () => void {
  const authInstance = getFirebaseAuth();
  if (!authInstance) {
    return () => {}; // Return empty unsubscribe function for SSR
  }
  return onAuthStateChanged(authInstance, callback);
}