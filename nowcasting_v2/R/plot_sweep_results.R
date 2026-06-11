# plot_sweep_results.R
# Build the morning-review graphs: best new-data v2 config vs current v2 (B0) vs
# v1 vs actual GDP, full-sample and post-COVID. Mirrors plot_v1_v2_backtest.R style.
# Usage: Rscript R/plot_sweep_results.R <best_variant_id>
source("R/_setup.R")
suppressMessages({ library(ggplot2); library(dplyr); library(tidyr) })

args <- commandArgs(trailingOnly = TRUE)
best_id <- if (length(args)) args[[1]] else {
  s <- read.csv("cache/sweep_v2/summary.csv")
  s$variant[order(s$rmse_pc)][1]
}
cat("Plotting best variant:", best_id, "\n")

qend <- function(q) {
  yr <- as.integer(substr(q,1,4)); qn <- as.integer(substr(q,7,7))
  as.Date(sprintf("%d-%02d-01", yr, qn*3))
}

best <- read.csv(file.path("cache/sweep_v2", paste0(best_id, ".csv"))) |>
  transmute(q = target_quarter, Actual = qoq_actual, best = qoq_growth_forecast)
b0   <- read.csv("cache/sweep_v2/B0_baseline.csv") |>
  transmute(q = target_quarter, v2 = qoq_growth_forecast)
v1   <- read.csv("cache/v1_baseline_r3_backtest.csv") |>
  transmute(q = target_quarter, v1 = qoq_growth_forecast)

m <- best |> full_join(b0, by="q") |> full_join(v1, by="q") |>
  mutate(date = qend(q)) |> arrange(date)

long <- m |> pivot_longer(c(Actual, v1, v2, best), names_to="series", values_to="qoq") |>
  filter(!is.na(qoq))
long$series <- factor(long$series, levels=c("Actual","v1","v2","best"),
  labels=c("Actual GDP","v1 (13-series DFM)","v2 current (31-series)",
           paste0("v2 + survey data (", best_id, ")")))

pal <- c("Actual GDP"="grey15", "v1 (13-series DFM)"="#1f77b4",
         "v2 current (31-series)"="#9467bd")
pal[[paste0("v2 + survey data (", best_id, ")")]] <- "#e8702a"

mk <- function(df, sub) ggplot(df, aes(date, qoq, colour=series)) +
  geom_hline(yintercept=0, colour="grey80") +
  geom_line(aes(linewidth=series)) + geom_point(aes(size=series)) +
  scale_colour_manual(values=pal) +
  scale_linewidth_manual(values=c(1.7,0.8,0.8,1.0), guide="none") +
  scale_size_manual(values=c(2.5,1.4,1.4,1.8), guide="none") +
  labs(subtitle=sub, x=NULL, y="QoQ GDP growth (%)", colour=NULL) +
  theme_minimal(base_size=12) +
  theme(legend.position="top", panel.grid.minor=element_blank())

ggsave("v2_survey_backtest_full.png",
  mk(long, "Full backtest — v2 with long-history survey data vs current v2 vs v1 vs actual GDP"),
  width=10, height=4.8, dpi=150, bg="white")
ggsave("v2_survey_backtest_postcovid.png",
  mk(filter(long, date >= as.Date("2022-01-01")), "Post-COVID detail"),
  width=10, height=4.8, dpi=150, bg="white")
cat("wrote v2_survey_backtest_full.png + _postcovid.png ; rows=", nrow(m), "\n")
