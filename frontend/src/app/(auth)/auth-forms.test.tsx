import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, renderWithQuery } from "@/test/helpers";
import { LoginForm } from "./login/login-form";
import { RegisterForm } from "./register/register-form";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(),
}));

const USER = { id: "u1", email: "a@example.com", full_name: "Ada", created_at: "2026-01-01T00:00:00Z" };

beforeEach(() => replace.mockClear());

describe("LoginForm", () => {
  it("validates required fields without calling the API", async () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    renderWithQuery(<LoginForm />);
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Email is required")).toBeInTheDocument();
    expect(screen.getByText("Password is required")).toBeInTheDocument();
    expect(f).not.toHaveBeenCalled();
  });

  it("shows the server's error message on bad credentials", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      jsonResponse(401, { error: { code: "invalid_credentials", message: "Invalid email or password." } }),
    ));
    renderWithQuery(<LoginForm />);
    await userEvent.type(screen.getByLabelText("Email"), "a@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(replace).not.toHaveBeenCalled();
  });

  it("redirects to /dashboard on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, USER)));
    renderWithQuery(<LoginForm />);
    await userEvent.type(screen.getByLabelText("Email"), "a@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-9");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });
});

describe("RegisterForm", () => {
  it("enforces the 8-character minimum before submitting", async () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    renderWithQuery(<RegisterForm />);
    await userEvent.type(screen.getByLabelText("Email"), "a@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByText("Password must be at least 8 characters")).toBeInTheDocument();
    expect(f).not.toHaveBeenCalled();
  });

  it("surfaces a duplicate-email conflict from the API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      jsonResponse(409, { error: { code: "conflict", message: "An account with this email already exists." } }),
    ));
    renderWithQuery(<RegisterForm />);
    await userEvent.type(screen.getByLabelText("Email"), "a@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-9");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  });
});
