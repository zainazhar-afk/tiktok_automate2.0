"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Navbar() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold text-purple-400">TikTok</span>
          <span className="text-xl font-bold text-white">Automate</span>
          <span className="text-xs bg-purple-600/30 text-purple-300 px-2 py-0.5 rounded ml-2">
            BULK
          </span>
        </div>

        <div className="flex items-center gap-1">
          {[
            { href: "/", label: "Discover" },
            { href: "/bulk", label: "Bulk Edit" },
            { href: "/export", label: "Export" },
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
        </div>
      </div>
    </nav>
  );
}
