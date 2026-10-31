"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2 } from "lucide-react";
import { AuthCard, Field, FormError } from "@/components/layout/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useResetPassword } from "@/lib/auth";

const schema = z
  .object({
    password: z.string().min(8, "Password must be at least 8 characters").max(256, "Password is too long"),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });
type Values = z.infer<typeof schema>;

export function ResetForm() {
  const token = useSearchParams().get("token");
  const reset = useResetPassword();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  const signInLink = (
    <Link href="/login" className="font-medium text-primary hover:underline">
      Back to sign in
    </Link>
  );

  if (!token) {
    return (
      <AuthCard title="Link invalid" description="This reset link is missing its token." footer={signInLink}>
        <Link href="/forgot-password" className="text-center text-sm font-medium text-primary hover:underline">
          Request a new link
        </Link>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Choose a new password" description="Enter a new password for your account." footer={signInLink}>
      {reset.isSuccess ? (
        <p role="status" className="rounded-md border border-border bg-muted px-3 py-2 text-sm">
          {reset.data.message}
        </p>
      ) : (
        <form
          onSubmit={handleSubmit((v) => reset.mutate({ token, new_password: v.password }))}
          className="flex flex-col gap-4"
          noValidate
        >
          <FormError message={reset.error?.message} />
          <Field label="New password" htmlFor="password" error={errors.password?.message}>
            <Input id="password" type="password" autoComplete="new-password" aria-invalid={!!errors.password} {...register("password")} />
          </Field>
          <Field label="Confirm password" htmlFor="confirm" error={errors.confirm?.message}>
            <Input id="confirm" type="password" autoComplete="new-password" aria-invalid={!!errors.confirm} {...register("confirm")} />
          </Field>
          <Button type="submit" disabled={reset.isPending}>
            {reset.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            Update password
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
