"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, ChevronDown, Search, ShieldCheck } from "lucide-react";
import { clearSession, getStoredUser } from "@/lib/auth";
import { useRouter } from "next/navigation";

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const user = getStoredUser();

  const links = [
    { label: "Requisitions", href: "/jobs", active: pathname.startsWith("/jobs") },
  ];

  return (
    <header className="sticky top-0 z-30 w-full border-b border-line bg-white">
      <div className="mx-auto flex h-16 max-w-[1440px] items-center gap-8 px-6">
        <Link href="/jobs" className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white">
            <ShieldCheck className="h-5 w-5" aria-hidden="true" />
          </span>
          <span className="text-[22px] font-bold tracking-tight text-brand-600">HireFlow</span>
        </Link>

        <nav aria-label="Primary" className="hidden items-center gap-6 lg:flex">
          {links.map((link) => (
            <Link
              key={link.label}
              href={link.href}
              className={`text-[15px] transition-colors duration-150 hover:text-brand-600 ${
                link.active ? "font-semibold text-ink-900" : "text-ink-700"
              }`}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto hidden w-[340px] items-center gap-2 rounded-full border border-line bg-canvas px-4 py-2 md:flex">
          <Search className="h-4 w-4 shrink-0 text-ink-400" aria-hidden="true" />
          <input
            type="search"
            aria-label="Search candidates"
            placeholder="Search candidates or requisitions"
            className="w-full bg-transparent text-sm text-ink-900 outline-none placeholder:text-ink-400"
          />
        </div>

        <button
          type="button"
          className="relative rounded-full p-2 text-ink-500 transition-colors hover:bg-canvas hover:text-ink-900"
          aria-label="Notifications"
        >
          <Bell className="h-5 w-5" aria-hidden="true" />
        </button>

        <button
          type="button"
          onClick={() => {
            clearSession();
            router.replace("/login");
          }}
          className="flex items-center gap-2 rounded-full border border-line py-1 pl-1 pr-3 transition-colors hover:bg-canvas"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700">
            {(user?.name ?? "R")
              .split(" ")
              .map((p) => p[0])
              .join("")
              .slice(0, 2)
              .toUpperCase()}
          </span>
          <span className="hidden text-sm text-ink-700 sm:inline">{user?.name ?? "Recruiter"}</span>
          <ChevronDown className="h-4 w-4 text-ink-400" aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
