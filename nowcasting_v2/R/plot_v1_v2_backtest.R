source("R/_setup.R")
suppressMessages({ library(ggplot2); library(dplyr); library(tidyr) })

# Parse "YYYY Qn" -> quarter-end date for a common, convention-proof key.
qend <- function(q) {
  yr <- as.integer(substr(q, 1, 4)); qn <- as.integer(substr(q, 7, 7))
  as.Date(sprintf("%d-%02d-01", yr, qn*3))
}
v2 <- read.csv("cache/backtest_v2/backtest_results.csv") |>
  transmute(q = target_quarter, Actual = qoq_actual, v2 = qoq_growth_forecast)
v1 <- read.csv("cache/v1_baseline_r3_backtest.csv") |>
  transmute(q = target_quarter, v1 = qoq_growth_forecast)

m <- v2 |> full_join(v1, by = "q") |> mutate(date = qend(q)) |> arrange(date)

long <- m |> pivot_longer(c(Actual, v1, v2), names_to="series", values_to="qoq") |>
  filter(!is.na(qoq))
long$series <- factor(long$series, levels=c("Actual","v1","v2"),
  labels=c("Actual GDP","v1 (13-series DFM)","v2 (MAI → U-MIDAS)"))

mk <- function(df, sub) ggplot(df, aes(date, qoq, colour=series)) +
  geom_hline(yintercept=0, colour="grey80") +
  geom_line(aes(linewidth=series)) + geom_point(aes(size=series)) +
  scale_colour_manual(values=c("Actual GDP"="grey15",
     "v1 (13-series DFM)"="#1f77b4","v2 (MAI → U-MIDAS)"="#e8702a")) +
  scale_linewidth_manual(values=c(1.7,0.85,0.85), guide="none") +
  scale_size_manual(values=c(2.5,1.5,1.5), guide="none") +
  labs(subtitle=sub, x=NULL, y="QoQ GDP growth (%)", colour=NULL) +
  theme_minimal(base_size=12) +
  theme(legend.position="top", panel.grid.minor=element_blank())

ggsave("v2_vs_v1_backtest.png",
  mk(long, "Full backtest — v2 tracks the COVID shock; v1 backtest only spans 2020+"),
  width=10, height=4.6, dpi=150, bg="white")
ggsave("v2_vs_v1_backtest_postcovid.png",
  mk(filter(long, date >= as.Date("2022-01-01")),
     "Post-COVID detail — v1 hugs actual tighter in calm quarters (RMSE 0.34 vs 0.51pp); v2 closer on 2026 Q1"),
  width=10, height=4.6, dpi=150, bg="white")
cat("rows=", nrow(m), " v1 overlap=", sum(!is.na(m$v1)), " v2=", sum(!is.na(m$v2)), "\n")
