"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { setSession } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.register({
        email,
        password,
        name,
        org_name: orgName,
      });
      setSession(result.access_token, result.user);
      router.replace("/jobs");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center bg-canvas px-6">
      <div className="flex items-center gap-2">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-600 text-white">
          <ShieldCheck className="h-5 w-5" aria-hidden="true" />
        </span>
        <p className="text-2xl font-bold text-brand-600">HireFlow</p>
      </div>
      <p className="mt-2 text-sm text-ink-500">Create a recruiter workspace.</p>
      <form onSubmit={onSubmit} className="mt-8 space-y-4 rounded-xl border border-line bg-white p-6 shadow-[var(--shadow-card)]">
        <label className="block text-sm">
          Your name
          <input
            className="mt-1 w-full rounded-lg border border-line bg-canvas px-3 py-2 outline-none focus:border-brand-600 focus:bg-white"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </label>
        <label className="block text-sm">
          Organization
          <input
            className="mt-1 w-full rounded-lg border border-line bg-canvas px-3 py-2 outline-none focus:border-brand-600 focus:bg-white"
            value={orgName}
            onChange={(e) => setOrgName(e.target.value)}
            required
          />
        </label>
        <label className="block text-sm">
          Email
          <input
            className="mt-1 w-full rounded-lg border border-line bg-canvas px-3 py-2 outline-none focus:border-brand-600 focus:bg-white"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="block text-sm">
          Password (min 8 characters)
          <input
            className="mt-1 w-full rounded-lg border border-line bg-canvas px-3 py-2 outline-none focus:border-brand-600 focus:bg-white"
            type="password"
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="text-sm text-missing">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-brand-600 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
        >
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>
      <p className="mt-4 text-center text-sm text-ink-500">
        Already registered?{" "}
        <Link href="/login" className="font-medium text-brand-600 hover:text-brand-700">
          Sign in
        </Link>
      </p>
    </div>
  );
}
