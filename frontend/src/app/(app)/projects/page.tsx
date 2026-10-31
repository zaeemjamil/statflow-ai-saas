import type { Metadata } from "next";
import { ProjectsList } from "./projects-list";

export const metadata: Metadata = { title: "Projects" };

export default function ProjectsPage() {
  return <ProjectsList />;
}
