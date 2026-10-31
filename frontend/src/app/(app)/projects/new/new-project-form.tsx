"use client";

import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2 } from "lucide-react";
import { Field, FormError } from "@/components/layout/auth-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useCreateProject } from "@/lib/projects";

// Backend: name min 1 / max 255.
const schema = z.object({
  name: z.string().trim().min(1, "Give your project a name").max(255, "Name is too long (max 255)"),
});
type Values = z.infer<typeof schema>;

export function NewProjectForm() {
  const router = useRouter();
  const create = useCreateProject();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  return (
    <div className="mx-auto max-w-xl">
      <Card>
        <CardHeader>
          <CardTitle as="h1">New project</CardTitle>
          <CardDescription>You&apos;ll upload a CSV or Excel file in the next step.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-4"
            noValidate
            onSubmit={handleSubmit((v) =>
              create.mutate(v.name, { onSuccess: (p) => router.push(`/projects/${p.id}`) }),
            )}
          >
            <FormError message={create.error?.message} />
            <Field label="Project name" htmlFor="name" error={errors.name?.message}>
              <Input id="name" autoFocus placeholder="e.g. Q3 sensor readings" aria-invalid={!!errors.name} {...register("name")} />
            </Field>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              Create project
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
