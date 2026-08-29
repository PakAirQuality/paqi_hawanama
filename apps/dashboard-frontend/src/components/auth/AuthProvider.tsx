"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { User } from 'firebase/auth';
import { onAuthStateChange, isValidUser, signOut } from '@/lib/firebaseClient';

interface AuthContextType {
  user: User | null;
  loading: boolean;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  isAuthenticated: false,
});

export const useAuth = () => useContext(AuthContext);

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);

  // Handle hydration
  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;

    const unsubscribe = onAuthStateChange(async (user) => {
      if (user && !isValidUser(user)) {
        // User signed in but doesn't have valid domain - sign them out
        try {
          await signOut();
        } catch (error) {
          console.error('Sign out error:', error);
        }
        setUser(null);
      } else {
        setUser(user);
      }
      setLoading(false);
    });

    return unsubscribe;
  }, [mounted]);

  if (!mounted) {
    return <div className="min-h-screen flex items-center justify-center">
      <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-blue-600"></div>
    </div>;
  }

  const value: AuthContextType = {
    user,
    loading,
    isAuthenticated: !!user && isValidUser(user),
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}