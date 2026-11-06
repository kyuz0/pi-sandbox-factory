// Keep direct page retrieval on the separately reviewed fetch_content tool.
export function searchOnly(tool) {
  return {
    ...tool,
    description: tool.description + " Use fetch_content to download pages. Search runs with includeContent=false and workflow=none.",
    async execute(id, params, ...rest) {
      if (params.includeContent || (params.workflow && params.workflow !== "none")) {
        throw new Error("Search does not download result pages or run summary workflows in this sandbox. Retry with includeContent=false and workflow=none; use fetch_content to read a page through the configured approval policy.");
      }
      return tool.execute(id, { ...params, includeContent: false, workflow: "none" }, ...rest);
    },
  };
}
