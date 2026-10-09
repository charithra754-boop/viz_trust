import { useEffect } from "react";
import { useLocation } from "react-router-dom";

export default function ScrollToTop() {
  const { pathname } = useLocation();
  // Braces matter: newer browsers return a Promise from scrollTo, and an effect must return
  // nothing or a cleanup function. Returning the Promise crashes every page.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}
