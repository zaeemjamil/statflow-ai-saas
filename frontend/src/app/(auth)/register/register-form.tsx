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
import { useRegister } from "@/lib/auth";

// Mirrors the backend RegisterRequest limits (min 8 / max 256 password).
const schema = z.object({
  full_name: z.string().max(255, "Name is too long").optional(),
  email: z.string().min(1, "Email is required").email("Enter a valid email"),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters")
    .max(256, "Password is too long"),
});
type Values = z.infer<typeof schema>;

export function RegisterForm() {
  const router = useRouter();
  const registerUser = useRegister();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  const onSubmit = (v: Values) =>
    registerUser.mutate(
      { email: v.email, password: v.password, full_name: v.full_name?.trim() || undefined },
      { onSuccess: () => router.replace("/dashboard") },
    );

  return (
    <AuthCard
      title="Create your account"
      description="Start turning spreadsheets into decisions."
      footer={
        <>
          Already registered?{" "}
          <Link href="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
        <FormError message={registerUser.error?.message} />
        <Field label="Full name (optional)" htmlFor="full_name" error={errors.full_name?.message}>
          <Input id="full_name" autoComplete="name" {...register("full_name")} />
        </Field>
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message}>
          <Input id="password" type="password" autoComplete="new-password" aria-invalid={!!errors.password} {...register("password")} />
        </Field>
        <Button type="submit" disabled={registerUser.isPending}>
          {registerUser.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Create account
        </Button>
      </form>
    </AuthCard>
  );
}
