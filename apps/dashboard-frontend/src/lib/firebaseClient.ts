"use client";

import { initializeApp, getApp, getApps } from "firebase/app";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  onAuthStateChanged,
  signOut as fbSignOut,
  type User,
} from "firebase/auth";
import { getFirestore } from "firebase/firestore";
import { getStorage } from "firebase/storage";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY || '',
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || '',
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || '',
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET || '',
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID || '',
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID || '',
};

function assertConfig() {
  const missing = [];
  if (!firebaseConfig.apiKey) missing.push('NEXT_PUBLIC_FIREBASE_API_KEY');
  if (!firebaseConfig.authDomain) missing.push('NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN');
  if (!firebaseConfig.projectId) missing.push('NEXT_PUBLIC_FIREBASE_PROJECT_ID');
  if (!firebaseConfig.appId) missing.push('NEXT_PUBLIC_FIREBASE_APP_ID');
  
  if (missing.length > 0) {
    throw new Error(`Missing Firebase env vars in .env.local: ${missing.join(', ')}\n\nPlease:\n1. Go to Firebase Console → Project Settings → General → Your apps\n2. Copy the config values\n3. Set them in .env.local\n4. Rebuild: npm run build`);
  }
}

let provider: GoogleAuthProvider | null = null;

export function isConfigValid(): boolean {
  return !!(
    firebaseConfig.apiKey &&
    firebaseConfig.authDomain &&
    firebaseConfig.projectId &&
    firebaseConfig.appId
  );
}

function getFirebase() {
  if (!isConfigValid()) {
    throw new Error("Firebase configuration is incomplete. Please check your environment variables.");
  }

  const app = getApps().length ? getApp() : initializeApp(firebaseConfig);
  const auth = getAuth(app);
  const db = getFirestore(app);
  const storage = getStorage(app);

  if (!provider) {
    provider = new GoogleAuthProvider();
    provider.setCustomParameters({
      hd: "pakairquality.com", // hint only
      prompt: "select_account",
    });
  }

  return { auth, db, storage, provider };
}

const ALLOWED_EMAILS = new Set([
  "kaukabtahirshairani@gmail.com",
]);

export function isValidUser(user: User | null): boolean {
  if (!user || !user.email) return false;
  const email = user.email.toLowerCase();
  return user.emailVerified && (email.endsWith("@pakairquality.com") || ALLOWED_EMAILS.has(email));
}

export async function signInWithGoogle(): Promise<User> {
  if (!isConfigValid()) {
    throw new Error("Firebase configuration is incomplete. Please set up your environment variables.");
  }
  
  const { auth, provider } = getFirebase();
  const result = await signInWithPopup(auth, provider);
  const user = result.user;

  if (!isValidUser(user)) {
    await fbSignOut(auth);
    throw new Error("Access restricted to @pakairquality.com accounts only.");
  }
  return user;
}

export async function signOut() {
  if (!isConfigValid()) {
    return; // Gracefully handle missing config
  }
  
  const { auth } = getFirebase();
  await fbSignOut(auth);
}

export function onAuthStateChange(cb: (u: User | null) => void) {
  if (!isConfigValid()) {
    // Return a no-op unsubscribe function if config is invalid
    cb(null);
    return () => {};
  }
  
  const { auth } = getFirebase();
  return onAuthStateChanged(auth, (u) => {
    if (u && !isValidUser(u)) {
      fbSignOut(auth).finally(() => cb(null));
      return;
    }
    cb(u);
  });
}