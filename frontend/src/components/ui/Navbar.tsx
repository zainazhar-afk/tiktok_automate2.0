"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { getAccountStatus, type AccountStatus } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function Navbar() {
  const pathname = usePathname();
  const auth = useAuth();
  const [account, setAccount] = useState<AccountStatus | null>(null);

  useEffect(() => {
    let mounted = true;
    const timer = setTimeout(() => {
      if (auth.enabled && !auth.user) {
        if (mounted) setAccount(null);
        return;
      }
      getAccountStatus()
        .then((next) => {
          if (mounted) setAccount(next);
        })
        .catch(() => {
          if (mounted) setAccount(null);
        });
    }, 0);
    return () => {
      mounted = false;
      clearTimeout(timer);
    };
  }, [auth.enabled, auth.user]);

  return (
    <nav className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-50">
      <div className="mx-auto flex min-h-14 max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold text-purple-400">TikTok</span>
          <span className="text-xl font-bold text-white">Automate</span>
          <span className="text-xs bg-purple-600/30 text-purple-300 px-2 py-0.5 rounded ml-2">
            BULK
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-1">
          {[
            { href: "/", label: "Discover" },
            { href: "/bulk", label: "Bulk Edit" },
            { href: "/editor", label: "Editor" },
            { href: "/variants", label: "Variants" },
            { href: "/export", label: "Export" },
            { href: "/account", label: "Account" },
          ].map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                pathname === link.href
                  ? "bg-purple-600/20 text-purple-300"
                  : "text-gray-400 hover:text-white hover:bg-gray-800"
              }`}
            >
              {link.label}
            </Link>
          ))}
          {account && (
            <span className={`ml-1 rounded px-2 py-1 text-[11px] font-medium ${
              account.subscription_active ? "bg-green-600/20 text-green-200" : "bg-yellow-600/20 text-yellow-200"
            }`}>
              {account.plan}
            </span>
          )}
          {auth.enabled && auth.user && (
            <div className="ml-2 flex items-center gap-2 border-l border-gray-800 pl-3">
              <span className="max-w-40 truncate text-xs text-gray-400">
                {auth.user.email}
              </span>
              <button
                onClick={() => void auth.signOut()}
                className="rounded bg-gray-800 px-3 py-1.5 text-xs font-medium text-gray-200 hover:bg-gray-700"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
