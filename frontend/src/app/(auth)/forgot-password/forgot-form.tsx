"use client";

import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2 } from "lucide-react";
import { AuthCard, Field, FormError } from "@/components/layout/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useForgotPassword } from "@/lib/auth";

const schema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email"),
});
type Values = z.infer<typeof schema>;

export function ForgotForm() {
  const forgot = useForgotPassword();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  return (
    <AuthCard
      title="Reset your password"
      description="We'll email you a reset link if an account exists."
      footer={
        <Link href="/login" className="font-medium text-primary hover:underline">
          Back to sign in
        </Link>
      }
    >
      {forgot.isSuccess ? (
        <p role="status" className="rounded-md border border-border bg-muted px-3 py-2 text-sm">
          {forgot.data.message}
        </p>
      ) : (
        <form onSubmit={handleSubmit((v) => forgot.mutate(v))} className="flex flex-col gap-4" noValidate>
          <FormError message={forgot.error?.message} />
          <Field label="Email" htmlFor="email" error={errors.email?.message}>
            <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...register("email")} />
          </Field>
          <Button type="submit" disabled={forgot.isPending}>
            {forgot.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            Send reset link
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
