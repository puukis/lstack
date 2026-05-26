export type ThemeChoice = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "lstack:theme";
export const PREFERS_DARK_QUERY = "(prefers-color-scheme: dark)";

export function getThemeChoice(): ThemeChoice {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") {
    return stored;
  }
  return "system";
}

export function resolveTheme(choice: ThemeChoice): "light" | "dark" {
  if (choice !== "system") return choice;
  return window.matchMedia(PREFERS_DARK_QUERY).matches ? "dark" : "light";
}

export function applyThemeChoice(choice: ThemeChoice) {
  document.documentElement.dataset.theme = resolveTheme(choice);
  document.documentElement.dataset.themeChoice = choice;
}

export function storeThemeChoice(choice: ThemeChoice) {
  window.localStorage.setItem(THEME_STORAGE_KEY, choice);
  applyThemeChoice(choice);
}

export function nextThemeChoice(choice: ThemeChoice): ThemeChoice {
  if (choice === "system") return "dark";
  if (choice === "dark") return "light";
  return "system";
}
