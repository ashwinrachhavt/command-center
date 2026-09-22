export function useAuth() {
  return { isLoaded: true, userId: "synthetic-preview" };
}
export function UserButton() {
  return (
    <span
      aria-label="Synthetic account"
      className="flex size-7 items-center justify-center rounded-full bg-secondary text-xs"
    >
      A
    </span>
  );
}
