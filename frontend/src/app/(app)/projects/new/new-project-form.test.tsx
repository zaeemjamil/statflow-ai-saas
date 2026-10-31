import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { jsonResponse, mockApi, renderWithQuery } from "@/test/helpers";
import { NewProjectForm } from "./new-project-form";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

describe("NewProjectForm", () => {
  it("requires a name before calling the API", async () => {
    const api = mockApi({});
    renderWithQuery(<NewProjectForm />);
    await userEvent.click(screen.getByRole("button", { name: /create project/i }));
    expect(await screen.findByText("Give your project a name")).toBeInTheDocument();
    expect(api).not.toHaveBeenCalled();
  });

  it("creates the project and navigates to it", async () => {
    mockApi({
      "POST /projects": () =>
        jsonResponse(201, { id: "p9", name: "Sensors", status: "created", created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z" }),
    });
    renderWithQuery(<NewProjectForm />);
    await userEvent.type(screen.getByLabelText("Project name"), "  Sensors  ");
    await userEvent.click(screen.getByRole("button", { name: /create project/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects/p9"));
  });
});
