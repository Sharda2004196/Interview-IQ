"use client";

import { useEffect, useState } from "react";
import { initializeApp, getApps } from "firebase/app";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
  onAuthStateChanged,
  type User,
} from "firebase/auth";

// Public client config (safe to ship — Firebase docs pattern). Auths users
// against interviewiq-2768a; the backend verifies ID tokens server-side.
const firebaseConfig = {
  apiKey: "AIzaSyBk5pne4_uN5biuMOzrklt-kGdLqY1-vqc",
  authDomain: "interviewiq-2768a.firebaseapp.com",
  projectId: "interviewiq-2768a",
  storageBucket: "interviewiq-2768a.firebasestorage.app",
  messagingSenderId: "530507955205",
  appId: "1:530507955205:web:cfb5a69d9b09b71745306c",
};

const app = getApps().length > 0 ? getApps()[0] : initializeApp(firebaseConfig);
export const auth = getAuth(app);
const provider = new GoogleAuthProvider();

export async function signInWithGoogle(): Promise<void> {
  await signInWithPopup(auth, provider);
}

export async function signOutUser(): Promise<void> {
  await signOut(auth);
}

/** Current user's ID token, or null when logged out (logged-out = old behavior). */
export async function getIdToken(): Promise<string | null> {
  const u = auth.currentUser;
  if (!u) return null;
  try {
    return await u.getIdToken();
  } catch {
    return null;
  }
}

export function useFirebaseUser(): User | null | undefined {
  // undefined = still resolving (avoid sign-in flicker on load)
  const [user, setUser] = useState<User | null | undefined>(undefined);
  useEffect(() => onAuthStateChanged(auth, (u) => setUser(u)), []);
  return user;
}

export type { User };
