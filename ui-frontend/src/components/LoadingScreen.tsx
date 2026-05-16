import { useEffect, useState } from "react";

interface LoadingScreenProps {
  loaded: boolean;
}

export function LoadingScreen({ loaded }: LoadingScreenProps) {
  const [progress, setProgress] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (loaded) {
      setProgress(100);
      const timer = setTimeout(() => setVisible(false), 400);
      return () => clearTimeout(timer);
    }
    // Animate to 90% over 3 seconds using intervals
    const start = Date.now();
    const duration = 3000;
    const interval = setInterval(() => {
      const elapsed = Date.now() - start;
      const fraction = Math.min(elapsed / duration, 1);
      // Ease-out curve: fast start, slow finish
      const eased = 1 - Math.pow(1 - fraction, 3);
      setProgress(Math.round(eased * 90));
    }, 50);
    return () => clearInterval(interval);
  }, [loaded]);

  if (!visible) return null;

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center bg-slate-50 transition-opacity duration-300 ${loaded ? "opacity-0" : "opacity-100"}`}>
      <div className="w-80 text-center">
        <h1 className="text-xl font-bold text-slate-900 mb-6">Library QC</h1>
        <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-200 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="text-sm text-slate-500 mt-3">Loading library data...</p>
      </div>
    </div>
  );
}
