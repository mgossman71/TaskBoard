import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { AuthProvider } from "@/lib/auth";
import { ToastProvider } from "@/components/ui/Toast";
import { LoginPage, RegisterPage } from "@/pages/auth/AuthPages";
import { TaskCardBody } from "@/pages/project/BoardPage";
import { describeActivity } from "@/lib/activity";
import { task } from "@/test/fixtures";

function renderRoute(element: React.ReactElement, path = "/") {
  const router = createMemoryRouter([{ path, element }], { initialEntries: [path] });
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("auth forms", () => {
  it("shows accessible validation errors on the login form", async () => {
    renderRoute(<LoginPage />, "/login");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Email is required")).toBeInTheDocument();
    expect(screen.getByText("Password is required")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });

  it("enforces the password policy and confirmation on registration", async () => {
    renderRoute(<RegisterPage />, "/register");
    await userEvent.type(screen.getByLabelText("Your name"), "Ann");
    await userEvent.type(screen.getByLabelText("Email"), "ann@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "weakpassword");
    await userEvent.type(screen.getByLabelText("Confirm password"), "different");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText(/Include at least three of/)).toBeInTheDocument();
    expect(screen.getByText("Passwords do not match")).toBeInTheDocument();
  });
});

describe("task card", () => {
  it("renders key, priority, overdue and blocked states; escapes user content", () => {
    render(
      <TaskCardBody
        projectKey="WEB"
        task={task("x", "todo", 1, {
          number: 7,
          title: "<img src=x onerror=alert(1)>",
          priority: "urgent",
          due_date: "2000-01-01",
          blocked: true,
          labels: [{ id: "l", name: "bug", color: "#ff0000" }],
        })}
      />,
    );
    expect(screen.getByText("WEB-7")).toBeInTheDocument();
    expect(screen.getByText("urgent")).toBeInTheDocument();
    expect(screen.getByText("(overdue)")).toBeInTheDocument();
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("activity descriptions", () => {
  it("describes moves and assignments", () => {
    expect(describeActivity({ type: "task.moved", payload: { task: { number: 3, title: "T" }, from_column: { name: "A" }, to_column: { name: "B" } } }, "K")).toBe(
      'moved K-3 "T" from A to B',
    );
    expect(
      describeActivity({ type: "task.assigned", payload: { task: { number: 1, title: "T" }, changes: { assignees: { added: [{ name: "Bo" }], removed: [] } } } }),
    ).toBe('assigned Bo on "T"');
  });
});
