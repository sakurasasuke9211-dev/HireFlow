"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AiAssistant } from "@/components/AiAssistant";
import { TopNav } from "@/components/TopNav";
import { getToken } from "@/lib/auth";

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas text-sm text-ink-500">
        Loading…
      </div>
    );
  }

  return (
    <div className="min-h-full w-full bg-canvas font-sans">
      <TopNav />
      <main>{children}</main>
      <AiAssistant />
    </div>
  );
}
