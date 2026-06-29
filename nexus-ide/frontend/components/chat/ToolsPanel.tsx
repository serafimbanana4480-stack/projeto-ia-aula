"use client";
import { useToolsStore } from "../../stores/toolsStore";
import { getTools, toggleTool as toggleToolRemote } from "../../lib/api";
import { motion } from "framer-motion";
import { Wrench, Check } from "lucide-react";
import { useEffect } from "react";

const TOOLS = [
  { id: "read_file", name: "Read File", desc: "Read file contents" },
  { id: "write_file", name: "Write File", desc: "Write to files" },
  { id: "list_dir", name: "List Directory", desc: "List files and folders" },
  { id: "search_in_files", name: "Search Files", desc: "Search in codebase" },
  { id: "execute_code", name: "Execute Code", desc: "Run Python/JS/Bash" },
  { id: "web_search", name: "Web Search", desc: "Search the web" },
];

export default function ToolsPanel() {
  const { tools, setTools, toggleTool } = useToolsStore();

  useEffect(() => {
    // Initialize tools from backend
    const initializeTools = async () => {
      try {
        const data = await getTools();
        setTools(data);
      } catch (error) {
        console.error("Failed to fetch tools:", error);
      }
    };
    initializeTools();
  }, [setTools]);

  return (
    <motion.div
      initial={{ x: 20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      className="rounded border border-nexus-border bg-nexus-panel/50 p-3"
    >
      <div className="mb-3 flex items-center gap-2">
        <Wrench className="h-4 w-4 text-nexus-accent" />
        <span className="text-sm font-semibold">Active Tools</span>
      </div>
      
      <div className="space-y-2">
        {TOOLS.map((tool) => {
          const toolState = tools.find((t) => t.name === tool.id);
          const enabled = toolState?.enabled ?? true;
          
          return (
            <motion.button
              key={tool.id}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={async () => {
                toggleTool(tool.id);
                try {
                  await toggleToolRemote(tool.id, !enabled);
                } catch (error) {
                  console.error("Failed to toggle tool:", error);
                }
              }}
              className={`flex w-full items-center justify-between rounded border p-2 text-left transition-colors ${
                enabled
                  ? "border-nexus-border bg-nexus-border/30"
                  : "border-nexus-border/30 bg-transparent opacity-50"
              }`}
            >
              <div>
                <div className="text-xs font-medium">{tool.name}</div>
                <div className="text-xs text-gray-500">{tool.desc}</div>
              </div>
              {enabled && <Check className="h-4 w-4 text-nexus-accent" />}
            </motion.button>
          );
        })}
      </div>
    </motion.div>
  );
}
