"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getToken } from "@/lib/auth";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? "/jobs" : "/login");
  }, [router]);
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas text-sm text-ink-500">
      Loading…
    </div>
  );
}
