/**
 * Date grouping helper for conversation list
 * Groups into: Today, Yesterday, Previous 7 days, Older
 */
export function groupConversationsByDate(conversations, now = new Date()) {
  const groups = {
    today: [],
    yesterday: [],
    previous7Days: [],
    older: []
  };

  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const oneDayMs = 24 * 60 * 60 * 1000;
  const startOfYesterday = startOfToday - oneDayMs;
  const startOf7Days = startOfToday - 7 * oneDayMs;

  for (const conv of conversations) {
    const rawDate = conv.updated_at || conv.created_at;
    const itemDate = new Date(rawDate).getTime();

    if (isNaN(itemDate) || itemDate >= startOfToday) {
      groups.today.push(conv);
    } else if (itemDate >= startOfYesterday) {
      groups.yesterday.push(conv);
    } else if (itemDate >= startOf7Days) {
      groups.previous7Days.push(conv);
    } else {
      groups.older.push(conv);
    }
  }

  return groups;
}

/**
 * Maps privacy mode string to visual chip metadata
 */
export function getPrivacyChipInfo(mode) {
  switch (mode) {
    case "private":
      return {
        id: "private",
        label: "Private",
        tag: "Local only",
        description: "Local only, no memory storage, excluded from dataset training.",
        colorClass: "privacy-chip-private"
      };
    case "local_only":
      return {
        id: "local_only",
        label: "Local only",
        tag: "Offline",
        description: "Never routes to API; uses local Ollama models only.",
        colorClass: "privacy-chip-local"
      };
    case "standard":
    default:
      return {
        id: "standard",
        label: "Standard",
        tag: "Hybrid",
        description: "May use online API model for complex queries (logged by provider).",
        colorClass: "privacy-chip-standard"
      };
  }
}

/**
 * Formats model selection text including loading state
 */
export function formatModelDisplayName(modelName, isLoading = false) {
  if (!modelName) return "Select model";
  let display = modelName;
  if (modelName.includes("/")) {
    const parts = modelName.split("/");
    const short = parts[parts.length - 1].replace(":free", "");
    display = `${short} (API)`;
  }
  if (isLoading) {
    return `${display} (loading... ~15s)`;
  }
  return display;
}

