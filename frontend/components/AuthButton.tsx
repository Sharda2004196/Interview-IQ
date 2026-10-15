"use client";

import React, { useState } from "react";
import { GoogleLogo, SignOut } from "@phosphor-icons/react";
import { signInWithGoogle, signOutUser, useFirebaseUser } from "@/lib/firebase";
import { TOKENS } from "@/lib/tokens";

export function AuthButton({ className = "" }: { className?: string }) {
  const user = useFirebaseUser();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (user === undefined) {
    // Auth still resolving — reserve space, no flicker.
    return <div className={`w-9 h-9 ${TOKENS.radius.button}`} aria-hidden="true" />;
  }

  if (user === null) {
    return (
      <button
        type="button"
        disabled={busy}
        title={error || "Sign in with Google"}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await signInWithGoogle();
          } catch (err) {
            setError(err instanceof Error ? err.message : "Sign-in failed.");
          } finally {
            setBusy(false);
          }
        }}
        aria-label="Sign in with Google"
        className={`inline-flex items-center gap-1.5 px-3 h-9 ${TOKENS.radius.button} border border-zinc-200 dark:border-white/10 bg-zinc-100 hover:bg-zinc-200/80 dark:bg-zinc-900 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 text-xs font-semibold transition-all duration-150 active:scale-[0.98] disabled:opacity-60 ${className}`}
      >
        <GoogleLogo size={16} weight="bold" className="text-emerald-500" />
        <span className="hidden sm:inline">Sign in</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      title={user.email || "Signed in — click to sign out"}
      onClick={() => {
        signOutUser().catch(() => {
          // ignore — session ends locally regardless
        });
      }}
      aria-label={`Signed in as ${user.email || "user"} — sign out`}
      className={`inline-flex items-center gap-1.5 pl-1 pr-2.5 h-9 ${TOKENS.radius.button} border border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/20 text-zinc-800 dark:text-zinc-200 text-xs font-semibold transition-all duration-150 active:scale-[0.98] ${className}`}
    >
      {user.photoURL ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={user.photoURL} alt="" className="w-7 h-7 rounded-full" referrerPolicy="no-referrer" />
      ) : (
        <span className="w-7 h-7 rounded-full bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 flex items-center justify-center font-bold">
          {(user.email || "U").charAt(0).toUpperCase()}
        </span>
      )}
      <span className="hidden sm:inline max-w-[120px] truncate">
        {(user.email || "Account").split("@")[0]}
      </span>
      <SignOut size={14} weight="bold" className="text-zinc-500" />
    </button>
  );
}
