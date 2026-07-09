import { useState, useRef, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  researchChatApi,
  type ResearchChatTablePayload,
  type ResearchChatResponse,
} from "@/lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  table?: ResearchChatTablePayload;
}

export function ResearchChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [activeTable, setActiveTable] = useState<ResearchChatTablePayload | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const mutation = useMutation<ResearchChatResponse, Error, string>({
    mutationFn: (message) => researchChatApi.send({ message }),
    onSuccess: (data) => {
      setMessages((prev) => [
        ...prev.slice(0, -1),
        { role: "assistant", content: data.reply, table: data.table },
      ]);
      if (data.table) setActiveTable(data.table);
    },
    onError: () => {
      setMessages((prev) => [
        ...prev.slice(0, -1),
        { role: "assistant", content: "Something went wrong. Please try again." },
      ]);
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = () => {
    const text = input.trim();
    if (!text || mutation.isPending) return;
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ]);
    setInput("");
    mutation.mutate(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) send();
  };

  return (
    <div className="flex h-full gap-4 p-4">
      {/* Chat panel */}
      <div className="flex flex-col flex-1 border rounded-lg overflow-hidden bg-white">
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.length === 0 && (
            <p className="text-sm text-muted-foreground text-center mt-12">
              Ask anything about mutual fund schemes, holdings, or company exposure.
            </p>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[75%] px-4 py-2 rounded-2xl text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-foreground border whitespace-pre-wrap"
                }`}
              >
                {mutation.isPending && i === messages.length - 1 && msg.role === "assistant" ? (
                  <span className="text-muted-foreground animate-pulse">Thinking...</span>
                ) : (
                  msg.content
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <div className="flex gap-2 p-3 border-t bg-white">
          <input
            className="flex-1 border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about mutual funds..."
            disabled={mutation.isPending}
          />
          <button
            onClick={send}
            disabled={mutation.isPending || !input.trim()}
            className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium disabled:opacity-50 hover:bg-primary/90"
          >
            Send
          </button>
        </div>
      </div>

      {/* Results panel */}
      <div className="w-[480px] flex flex-col border rounded-lg overflow-hidden">
        <div className="p-3 border-b bg-muted/40">
          <h3 className="text-sm font-semibold text-muted-foreground">Results</h3>
        </div>
        <div className="flex-1 overflow-auto p-3">
          {activeTable ? (
            <ResultsTable table={activeTable} />
          ) : (
            <p className="text-sm text-muted-foreground text-center mt-12">
              Results will appear here after your first query.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function ResultsTable({ table }: { table: ResearchChatTablePayload }) {
  return (
    <div className="overflow-auto rounded-md border text-xs">
      <table className="w-full">
        <thead>
          <tr className="bg-muted">
            {table.columns.map((col) => (
              <th key={col} className="px-3 py-2 text-left font-semibold whitespace-nowrap border-b">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i} className="border-t hover:bg-muted/40">
              {table.columns.map((col) => (
                <td key={col} className="px-3 py-1.5 whitespace-nowrap">
                  {String(row[col] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
