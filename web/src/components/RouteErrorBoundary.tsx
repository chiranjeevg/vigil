import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
};

type State = { error: Error | null };

/**
 * Catches render errors in route content so a failed page (e.g. Settings) never
 * leaves the user with a blank shell with no recovery affordance.
 */
export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("RouteErrorBoundary:", error.message, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      const msg = this.state.error.message;
      return (
        <div className="rounded-xl border border-red-300/70 bg-red-50 p-6 dark:border-red-900/60 dark:bg-red-950/40">
          <h2 className="text-lg font-semibold text-red-900 dark:text-red-200">
            This page crashed
          </h2>
          <p className="mt-2 text-sm text-red-800/95 dark:text-red-300/90">
            {msg || "An unexpected error occurred while rendering."}
          </p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-500"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
