# Shared setup for v2 scripts.
# v2 lives outside pipeline/'s renv project, so the pipeline renv library (which
# holds midasr, readabs, pdftools, rvest, seasonal, etc.) isn't on .libPaths when
# we run from nowcasting_v2/. Prepend it. source("_setup.R") at the top of every
# v2 R script (or source the path relative to your cwd).
local({
  candidates <- c(
    "C:/Users/wilso/Documents/Claude/Projects/nowcasting/pipeline/renv/library/windows/R-4.5/x86_64-w64-mingw32",
    "../../pipeline/renv/library/windows/R-4.5/x86_64-w64-mingw32",
    "../pipeline/renv/library/windows/R-4.5/x86_64-w64-mingw32",
    "pipeline/renv/library/windows/R-4.5/x86_64-w64-mingw32"
  )
  for (p in candidates) if (dir.exists(p)) { .libPaths(c(normalizePath(p), .libPaths())); break }
})
