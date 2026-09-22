"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Assistant lives in the floating panel — redirect legacy route. */
export default function FilesRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/jobs");
  }, [router]);
  return null;
}
