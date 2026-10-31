"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Check, Pencil, Trash2, X } from "lucide-react";
import { StatusBadge } from "@/components/projects/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDeleteProject, useRenameProject } from "@/lib/projects";
import type { Project } from "@/lib/schemas";

export function ProjectHeader({ project }: { project: Project }) {
  const router = useRouter();
  const rename = useRenameProject(project.id);
  const del = useDeleteProject(project.id);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(project.name);
  const [confirming, setConfirming] = useState(false);

  const trimmed = name.trim();
  const canSave = trimmed.length > 0 && trimmed.length <= 255 && trimmed !== project.name;
  const error = rename.error?.message ?? del.error?.message;

  function save() {
    if (!canSave) return;
    rename.mutate(trimmed, { onSuccess: () => setEditing(false) });
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {editing ? (
          <form
            className="flex min-w-0 flex-1 items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              save();
            }}
          >
            <Input aria-label="Project name" value={name} maxLength={255} autoFocus onChange={(e) => setName(e.target.value)} />
            <Button type="submit" size="icon" aria-label="Save name" disabled={!canSave || rename.isPending}>
              <Check className="h-4 w-4" aria-hidden />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Cancel rename"
              onClick={() => {
                setEditing(false);
                setName(project.name);
                rename.reset();
              }}
            >
              <X className="h-4 w-4" aria-hidden />
            </Button>
          </form>
        ) : (
          <div className="flex min-w-0 items-center gap-3">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{project.name}</h1>
            <StatusBadge status={project.status} />
            <Button
              variant="ghost"
              size="icon"
              aria-label="Rename project"
              onClick={() => {
                setName(project.name);
                setEditing(true);
              }}
            >
              <Pencil className="h-4 w-4" aria-hidden />
            </Button>
          </div>
        )}

        {confirming ? (
          <div className="flex items-center gap-2" role="group" aria-label="Confirm deletion">
            <span className="text-sm text-muted-foreground">Delete this project and its file?</span>
            <Button
              variant="outline"
              size="sm"
              className="border-destructive text-destructive hover:bg-destructive/10"
              disabled={del.isPending}
              onClick={() => del.mutate(undefined, { onSuccess: () => router.replace("/projects") })}
            >
              Yes, delete
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button variant="outline" size="sm" onClick={() => setConfirming(true)}>
            <Trash2 className="h-4 w-4" aria-hidden />
            Delete
          </Button>
        )}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
