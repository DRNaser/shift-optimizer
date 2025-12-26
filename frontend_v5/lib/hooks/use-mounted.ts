"use client";

import { useState, useEffect } from "react";

/**
 * SSR Safety Hook
 * Returns true only after component has mounted on client.
 * Use this to wrap any client-only logic that could cause hydration errors.
 */
export function useMounted(): boolean {
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
    }, []);

    return mounted;
}
