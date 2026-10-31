import type { Metadata } from "next";
import { Suspense } from "react";
import { LoadingBlock } from "@/components/ui/state";
import { ProjectView } from "./project-view";

export const metadata: Metadata = { title: "Project" };

export default function ProjectPage({ params }: PageProps<"/projects/[id]">) {
  return (
    <Suspense fallback={<LoadingBlock label="Loading project" />}>
      <ProjectView params={params} />
    </Suspense>
  );
}
