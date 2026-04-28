type LoadingScreenProps = {
  label: string;
};

export function LoadingScreen({ label }: LoadingScreenProps) {
  return (
    <main className="flex min-h-[100svh] items-center justify-center bg-[#f3f6f9] px-4 text-[#1f2937]">
      <div className="flex items-center gap-3 rounded-md border border-[#cfdbe7] bg-white px-4 py-3 shadow-[0_18px_42px_rgba(15,42,67,0.12)]">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#cfdbe7] border-t-[#0c4f86]" />
        <span className="text-sm font-semibold">{label}</span>
      </div>
    </main>
  );
}

