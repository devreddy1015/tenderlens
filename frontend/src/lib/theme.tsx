import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const ThemeContext = createContext<{ choice: ThemeChoice; dark: boolean; setChoice: (t: ThemeChoice) => void }>({
  choice: "system",
  dark: false,
  setChoice: () => {},
});

function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem("theme");
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function systemDark(): boolean {
  return typeof matchMedia !== "undefined" && matchMedia("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readChoice);
  const [sysDark, setSysDark] = useState(systemDark);

  useEffect(() => {
    if (typeof matchMedia === "undefined") return;
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setSysDark(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const dark = choice === "dark" || (choice === "system" && sysDark);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const setChoice = (t: ThemeChoice) => {
    setChoiceState(t);
    try {
      if (t === "system") localStorage.removeItem("theme");
      else localStorage.setItem("theme", t);
    } catch {
      /* private mode: the choice lasts for this visit only */
    }
  };

  return <ThemeContext.Provider value={{ choice, dark, setChoice }}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);
