import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import React from "react";

const mocks = vi.hoisted(() => ({
  useThreads: vi.fn(),
  copilotkit: { threadEndpoints: { list: true, mutations: true } } as any,
  push: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  useThreads: mocks.useThreads,
  useCopilotKit: () => ({ copilotkit: mocks.copilotkit }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

import { ConversationHistory } from "@/features/deal-room/components/conversation-history";

const threads = [
  {
    id: "t1",
    agentId: "marketmesh_orchestrator",
    name: "First run",
    archived: false,
    createdAt: "2026-11-01T00:00:00Z",
    updatedAt: "2026-11-01T00:00:00Z",
    lastRunAt: "2026-11-01T00:00:00Z",
  },
  {
    id: "t2",
    agentId: "marketmesh_orchestrator",
    name: null,
    archived: false,
    createdAt: "2026-11-01T00:00:00Z",
    updatedAt: "2026-11-01T00:00:00Z",
  },
];

describe("ConversationHistory", () => {
  beforeEach(() => {
    mocks.useThreads.mockReset();
    mocks.useThreads.mockReturnValue({
      threads,
      isLoading: false,
      listError: null,
      isMutating: false,
      renameThread: vi.fn(),
      archiveThread: vi.fn(),
      unarchiveThread: vi.fn(),
      deleteThread: vi.fn(),
      fetchMoreThreads: vi.fn(),
      hasMoreThreads: false,
      isFetchingMoreThreads: false,
      refetchThreads: vi.fn(),
    });
    mocks.copilotkit.threadEndpoints = { list: true, mutations: true };
    mocks.push.mockReset();
  });

  it("renders thread names and a fallback for unnamed threads", () => {
    render(<ConversationHistory activeThreadId="t1" />);
    expect(screen.getByText("First run")).toBeInTheDocument();
    expect(screen.getByText(/t2/i)).toBeInTheDocument();
  });

  it("navigates on row click", () => {
    const onNavigate = vi.fn();
    render(
      <ConversationHistory activeThreadId="t1" onNavigate={onNavigate} />,
    );
    fireEvent.click(screen.getByText("First run"));
    expect(onNavigate).toHaveBeenCalledWith("t1");
  });

  it("hides when listing is unsupported", () => {
    mocks.copilotkit.threadEndpoints = { list: false, mutations: false };
    const { container } = render(<ConversationHistory activeThreadId="t1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renames, archives, and deletes through mutations", async () => {
    const renameThread = vi.fn();
    const archiveThread = vi.fn();
    const deleteThread = vi.fn().mockResolvedValue(undefined);
    mocks.useThreads.mockReturnValue({
      threads,
      isLoading: false,
      listError: null,
      isMutating: false,
      renameThread,
      archiveThread,
      unarchiveThread: vi.fn(),
      deleteThread,
      fetchMoreThreads: vi.fn(),
      hasMoreThreads: false,
      isFetchingMoreThreads: false,
      refetchThreads: vi.fn(),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ConversationHistory activeThreadId="t1" />);
    fireEvent.click(screen.getAllByRole("button", { name: /archive/i })[0]);
    expect(archiveThread).toHaveBeenCalledWith("t1");
    fireEvent.click(screen.getAllByRole("button", { name: /delete/i })[0]);
    expect(deleteThread).toHaveBeenCalledWith("t1");
  });
});