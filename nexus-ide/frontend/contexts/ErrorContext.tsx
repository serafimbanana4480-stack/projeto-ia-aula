"use client";

import { createContext, useContext, useState, ReactNode, useCallback } from "react";
import { errorLogger } from "../lib/errorLogger";

interface ErrorInfo {
  message: string;
  details?: any;
  timestamp: Date;
}

interface ErrorContextType {
  errors: ErrorInfo[];
  addError: (message: string, details?: any) => void;
  clearErrors: () => void;
  removeError: (index: number) => void;
}

const ErrorContext = createContext<ErrorContextType | undefined>(undefined);

export function ErrorProvider({ children }: { children: ReactNode }) {
  const [errors, setErrors] = useState<ErrorInfo[]>([]);

  const addError = useCallback((message: string, details?: any) => {
    const errorInfo: ErrorInfo = {
      message,
      details,
      timestamp: new Date(),
    };

    setErrors((prev) => [...prev.slice(-4), errorInfo]); // Keep last 5 errors

    // Log to error logger
    errorLogger.log(new Error(message), { details });
  }, []);

  const clearErrors = useCallback(() => {
    setErrors([]);
  }, []);

  const removeError = useCallback((index: number) => {
    setErrors((prev) => prev.filter((_, i) => i !== index));
  }, []);

  return (
    <ErrorContext.Provider value={{ errors, addError, clearErrors, removeError }}>
      {children}
    </ErrorContext.Provider>
  );
}

export function useErrorContext() {
  const context = useContext(ErrorContext);
  if (!context) {
    throw new Error("useErrorContext must be used within ErrorProvider");
  }
  return context;
}
