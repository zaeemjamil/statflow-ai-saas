"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2 } from "lucide-react";
import { AuthCard, Field, FormError } from "@/components/layout/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLogin } from "@/lib/auth";
import { safeNextPath } from "@/lib/safe-next";

const schema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email"),
  password: z.string().min(1, "Password is required"),
});
type Values = z.infer<typeof schema>;

/** Only same-origin relative paths are honored, to avoid open redirects. */
function safeNext(): string {
  return safeNextPath(new URLSearchParams(window.location.search).get("next"));
}

export function LoginForm() {
  const router = useRouter();
  const login = useLogin();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  const onSubmit = (v: Values) =>
    login.mutate(v, { onSuccess: () => router.replace(safeNext()) });

  return (
    <AuthCard
      title="Welcome back"
      description="Sign in to your Zaimex account."
      footer={
        <>
          No account?{" "}
          <Link href="/register" className="font-medium text-primary hover:underline">
            Create one
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
        <FormError message={login.error?.message} />
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message}>
          <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!errors.password} {...register("password")} />
        </Field>
        <div className="text-right text-sm">
          <Link href="/forgot-password" className="text-muted-foreground hover:text-foreground hover:underline">
            Forgot password?
          </Link>
        </div>
        <Button type="submit" disabled={login.isPending}>
          {login.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Sign in
        </Button>
      </form>
    </AuthCard>
  );
}
