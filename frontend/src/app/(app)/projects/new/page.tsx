import type { Metadata } from "next";
import { NewProjectForm } from "./new-project-form";

export const metadata: Metadata = { title: "New project" };

export default function NewProjectPage() {
  return <NewProjectForm />;
}
