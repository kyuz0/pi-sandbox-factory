import webAccess from "./node_modules/pi-web-access/dist/index.js";
import { searchOnly } from "./search-policy.mjs";

export default function (pi) {
  return webAccess({
    ...pi,
    registerTool(tool) {
      pi.registerTool(tool.name === "web_search" ? searchOnly(tool) : tool);
    },
  });
}
