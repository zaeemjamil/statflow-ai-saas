import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, renderWithQuery } from "@/test/helpers";
import { LoginForm } from "./login-form";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(),
}));

const USER = { id: "u1", email: "a@example.com", full_name: "Ada", created_at: "2026-01-01T00:00:00Z" };

async function signInWithNext(search: string) {
  window.history.pushState({}, "", `/login${search}`);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, USER)));
  renderWithQuery(<LoginForm />);
  await userEvent.type(screen.getByLabelText("Email"), "a@example.com");
  await userEvent.type(screen.getByLabelText("Password"), "correct-horse-9");
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
  await waitFor(() => expect(replace).toHaveBeenCalledTimes(1));
  return replace.mock.calls[0][0] as string;
}

beforeEach(() => replace.mockClear());
afterEach(() => window.history.pushState({}, "", "/"));

describe("LoginForm post-login redirect", () => {
  it.each([
    ["?next=/%255Cevil.com", "decodes to /%5Cevil.com"],
    ["?next=%2F%5Cevil.com", "decodes to /\\evil.com"],
    ["?next=%2F%09%2Fevil.com", "decodes to a tab between slashes"],
    ["?next=%2F%2Fevil.com", "decodes to //evil.com"],
    ["?next=https%3A%2F%2Fevil.com", "absolute URL"],
    ["?next=%2F%0A%2Fevil.com", "decodes to a newline between slashes"],
  ])("falls back to /dashboard for %s (%s)", async (search) => {
    expect(await signInWithNext(search)).toBe("/dashboard");
  });

  it("follows a legitimate internal path", async () => {
    expect(await signInWithNext("?next=%2Fprojects%2Fabc-123")).toBe("/projects/abc-123");
  });

  it("goes to /dashboard when there is no next parameter", async () => {
    expect(await signInWithNext("")).toBe("/dashboard");
  });
});
