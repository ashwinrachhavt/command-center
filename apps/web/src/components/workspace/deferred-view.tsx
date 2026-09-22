"use client";

import {
  Component,
  Suspense,
  lazy,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { Button } from "@/components/ui/button";
import { Spinner } from "./primitives";

class ViewBoundary extends Component<
  {
    children: ReactNode;
    label: string;
    onRetry: () => void;
  },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="rounded-lg border border-border p-4 text-sm">
        <p>Could not load {this.props.label}.</p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="mt-3"
          onClick={this.props.onRetry}
        >
          Try again
        </Button>
      </div>
    );
  }
}

/** Declare at module scope. Ordinary rerenders retain the loaded view and its state. */
export function deferView<Props extends object>(
  load: () => Promise<{ default: ComponentType<Props> }>,
  label: string,
) {
  const InitialView = lazy(load);
  return function DeferredView(props: Props) {
    const [attempt, setAttempt] = useState({ number: 0, View: InitialView });
    const View = attempt.View;
    return (
      <ViewBoundary
        key={attempt.number}
        label={label}
        onRetry={() =>
          setAttempt((current) => ({
            number: current.number + 1,
            View: lazy(load),
          }))
        }
      >
        <Suspense
          fallback={
            <div
              role="status"
              className="flex items-center gap-2 py-4 text-sm text-muted-foreground"
            >
              <Spinner />
              Loading {label}…
            </div>
          }
        >
          <View {...props} />
        </Suspense>
      </ViewBoundary>
    );
  };
}
