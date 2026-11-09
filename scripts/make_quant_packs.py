"""Create 8 editable quant-research exercise packs. Run once from DataGym root.

This generator never changes core.json or your SQLite progress database.
After generation, edit the resulting JSON files directly if you wish.
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
packs: dict[str, list[dict]] = defaultdict(list)


def q(track, code, title, level, kind, instruction, reference, steps, *, params=None, ds=None, hint=None):
    sections = []
    for segment in steps.split('||'):
        fragment, meaning = segment.split('::', 1)
        sections.append({'code': fragment.strip(), 'meaning': meaning.strip()})
    record = {
        'id': 'q-' + code,
        'title': title,
        'category': track,
        'difficulty': level,
        'dataset': ds or {'kind': kind},
        'instructions': instruction,
        'reference': reference,
        'hint': hint or ('Work inside out. ' + sections[0]['meaning']),
        'explanation': sections,
    }
    if params:
        record['parameters'] = {k: {'choices': v} for k, v in params.items()}
    packs[track].append(record)

# 1: Data Cleaning & Alignment — selection and repair of data before research
T = 'Data Cleaning & Alignment'
q(T,'prices-ge-filter','Exclude illiquid prices',2,'stocks','Return ticker prices where volume is at least {minvol} and price is strictly greater than {minprice}, sorted by price descending.',
  'df.loc[df["volume"].ge({minvol}) & df["price"].gt({minprice}), ["price", "volume"]].sort_values("price", ascending=False)',
  'ge / gt::Each comparison builds one Boolean per ticker, inclusive for ge and exclusive for gt.||&::Keep rows satisfying BOTH checks.||.loc + .sort_values::Extract the two columns and then rank surviving names by price.',params={'minvol':[150,300,450],'minprice':[70,150,220]})
q(T,'stocks-index-sort','Ticker lookup table',2,'trades','Create one row per symbol with its total quantity, indexed by ticker and ordered alphabetically.',
  'df.groupby("symbol", as_index=False)["qty"].sum().set_index("symbol").sort_index()',
  'groupby + sum::Collapse all trade records for each ticker into one quantity total.||set_index("symbol")::Convert the ticker column into the semantic row index.||sort_index()::Sort by ticker label, not by the total quantity.')
q(T,'price-fill-forward','Repair a price feed',3,'price_panel','Forward-fill missing prices, then return the most recent 6 observation rows.',
  'df.ffill().tail(6)',
  'ffill()::Fill each missing entry using the most recent earlier price in that asset. This is causal; bfill would import future data.||tail(6)::Keep the final six dates after filling the gaps.')
q(T,'price-return-no-fill','Price returns without hidden fills',3,'price_panel','Calculate simple asset returns from prices without implicitly filling missing observations. Drop dates containing any missing return.',
  'df.pct_change(fill_method=None).dropna(how="any")',
  'pct_change(fill_method=None)::For each asset compute P_t/P_(t-1)-1; leaving missing prices missing avoids artificial zero-return observations.||dropna(how="any")::Delete dates without a complete cross-sectional return vector.')
q(T,'price-nonmissing-count','Data completeness report',2,'price_panel','Return a descending Series of non-missing price observations for each asset.',
  'df.count().sort_values(ascending=False)',
  'count()::Count valid time points independently in each column, ignoring NaNs.||sort_values()::Place assets with the strongest history first.')
q(T,'price-availability-mask','Find incomplete histories',2,'price_panel','Return a Boolean DataFrame identifying missing-price cells, but only for dates on which at least one price is missing.',
  'df.isna().loc[lambda m: m.any(axis=1)]',
  'isna()::Build one Boolean per date and asset, true exactly when an observation is missing.||any(axis=1)::For each date, test whether at least one of its assets is missing.||loc[lambda m: ...]::Use that date-level mask to keep only rows with incomplete cross-sectional data.')
q(T,'panel-set-index','MultiIndex research panel',3,'asset_panel','Index the panel by date then ticker, sort both levels, and return only ret and volume columns.',
  'df.set_index(["date", "ticker"]).sort_index()[["ret", "volume"]]',
  'set_index(["date", "ticker"])::Convert two columns into a hierarchical index so every (date,ticker) pair is an address.||sort_index()::Sort both index levels, enabling predictable date/ticker slicing.||[[...]]::Keep only measured return and volume, without losing the MultiIndex.')
q(T,'panel-xs-name','Instrument history from a panel',3,'asset_panel','Return AAPL date-by-date close and return as a two-column DataFrame, indexed by date.',
  'df.set_index(["date", "ticker"]).xs("AAPL", level="ticker")[["close", "ret"]]',
  'set_index::Give date and ticker index levels distinct meanings.||xs("AAPL", level="ticker")::Cross-section the ticker dimension, leaving only the date index.||[["close", "ret"]]::Retain both requested series in a DataFrame.')
q(T,'panel-reindex-grid','Restore canonical ticker order',4,'asset_panel','Create a date-by-ticker close-price matrix whose columns appear in the order JPM, NVDA, MSFT, AAPL.',
  'df.pivot(index="date", columns="ticker", values="close").reindex(columns=["JPM", "NVDA", "MSFT", "AAPL"])',
  'pivot::Turn long (date,ticker) rows into a two-axis price matrix.||reindex(columns=...)::Rearrange columns by the desired economic order, not alphabetically; absent labels would introduce NaNs.')
q(T,'prices-same-day-bounds','Outlier clipping',3,'xi_state','Cap each signal at -{cap} and +{cap}, then return only days whose capped signal is strictly positive.',
  'df["signal"].clip(-{cap}, {cap}).loc[lambda s: s.gt(0)]',
  'clip::Apply symmetric limits to each signal without changing its index.||loc[lambda s: s.gt(0)]::Build the Boolean mask on the clipped Series itself; lambda passes the current object into the selection.',params={'cap':[0.5,0.8,1.0]})
q(T,'panel-query-volume','Screen a long panel',2,'asset_panel','From Tech names with volume >= {minimum}, keep date, ticker, volume and sort within date by ticker.',
  'df.query("sector == \'Tech\' and volume >= {minimum}")[["date", "ticker", "volume"]].sort_values(["date", "ticker"])',
  'query::Evaluate a row filter using column names directly, producing an index-aligned subset.||[[...]]::Project only the requested columns.||sort_values([...])::Sort first by date and then by ticker inside each date.',params={'minimum':[200,350,500]})
q(T,'stocks-where','Keep only valid returns',3,'stocks','Return the daily return Series, setting returns of stocks with volume below {minimum} to NaN instead of dropping tickers.',
  'df["return_1d"].where(df["volume"].ge({minimum}))',
  'where(mask)::Retain each return where its ticker passes the volume test. Rows that fail become NaN; the index stays unchanged.||ge({minimum})::Inclusive comparison constructs the condition using a different column.',params={'minimum':[200,350,500]})

# 2: Vectorized Feature Engineering
T = 'Feature Engineering'
q(T,'panel-liquidity-rank','Liquidity percentile by session',3,'asset_panel','For every trading day, append a new column liq_pct with the percentile rank of volume within that same day.',
  'df.assign(liq_pct=df.groupby("date")["volume"].rank(pct=True))',
  'groupby("date")["volume"].rank(pct=True)::Rank tickers only against other tickers on the same day, and express rank on the 0–1 percentile scale.||assign(liq_pct=...)::Attach one percentile to each original row, preserving the long panel.')
q(T,'panel-demean-returns','Cross-sectional residual returns',3,'asset_panel','Return a Series of each asset return minus the mean return of assets traded on the same date.',
  'df["ret"] - df.groupby("date")["ret"].transform("mean")',
  'groupby(...).transform("mean")::Broadcast the per-date average back to every row on that date; transform preserves the original row count.||df["ret"] - ...::Subtract the contemporaneous cross-sectional mean from each observation.')
q(T,'panel-sector-demean','Sector-neutral residual returns',4,'asset_panel','Return returns after removing each date-and-sector mean return, preserving the original row order.',
  'df["ret"] - df.groupby(["date", "sector"])["ret"].transform("mean")',
  'groupby([date, sector])::Form groups specific to each session AND sector; the same sector on another date is a different group.||transform("mean")::Align each group mean back with the original rows.||subtract::Create residual returns with no inadvertent reordering.')
q(T,'panel-returns-buckets','Cross-sectional trade candidates',4,'asset_panel','For each date, retain only the two highest-volume tickers; return date, ticker and volume sorted by date and descending volume.',
  'df.sort_values(["date", "volume"], ascending=[True, False]).groupby("date", sort=False).head(2)[["date", "ticker", "volume"]]',
  'sort_values([date,volume])::Put each day in order and move the most liquid stocks first within its day.||groupby("date").head(2)::Select two rows FROM EACH DATE, not just two rows in total.||[[...]]::Project only the requested columns.')
q(T,'panel-normalize-risk','Normalize factor exposures',4,'asset_panel','Return a Series of beta divided by its date-level mean beta (one normalized exposure per row).',
  'df["beta"] / df.groupby("date")["beta"].transform("mean")',
  'groupby(date).transform(mean)::Replicate the average beta for each date alongside every asset exposure.||division::Normalize each asset by its own date benchmark, without a loop.')
q(T,'panel-vector-notional','Dollar-volume feature matrix',3,'asset_panel','Compute close × volume for each record, pivot into dates × tickers, and sort the columns alphabetically.',
  'df.assign(dollar_volume=df["close"] * df["volume"]).pivot(index="date", columns="ticker", values="dollar_volume").sort_index(axis=1)',
  'assign::Multiply price and quantity row-by-row to build a turnover proxy.||pivot::Make a date-by-ticker feature matrix from the long panel.||sort_index(axis=1)::Sort ticker columns, leaving date rows intact.')
q(T,'xi-feature-zscore','Standardized latent-state signal',3,'xi_state','Return a Series of the signal standardized using its entire sample mean and population standard deviation.',
  '(df["signal"] - df["signal"].mean()) / df["signal"].std(ddof=0)',
  'mean()::Compute the scalar signal center.||std(ddof=0)::Use population standard deviation (not pandas default ddof=1).||vector arithmetic::Subtract center and divide scale at every date. This full-sample version is descriptive, NOT safe for live trading.')
q(T,'xi-causal-zscore','Causal z-score feature',5,'xi_state','Return signal minus its previous 5-day mean, divided by its previous 5-day std; use at least 3 earlier observations.',
  '(df["signal"] - df["signal"].shift(1).rolling(5, min_periods=3).mean()) / df["signal"].shift(1).rolling(5, min_periods=3).std()',
  'shift(1)::Make historical window end at yesterday, avoiding current-day information leakage.||rolling(5,min_periods=3)::Form trailing windows, requiring three past observations.||mean / std::Measure current signal relative to a strictly historical distribution.')
q(T,'xi-conditional-forecast','Regime-weighted forecast',4,'xi_state','Return a Series of probability-weighted forecasts, treating the stress-regime forecast as -0.5 × forecast.',
  'df["p_risk"] * df["forecast"] + df["p_stress"] * (-0.5 * df["forecast"])',
  'p_risk and p_stress::Probabilities form the time-dependent mixture weights.||weighted sum::Combine one optimistic forecast and a scaled defensive forecast elementwise across dates.')
q(T,'xi-clip-and-lag','Bounded trading signal',4,'xi_state','Cap the signal at ±{cap}, then lag it by one session to construct next-day usable exposure.',
  'df["signal"].clip(lower=-{cap}, upper={cap}).shift(1)',
  'clip::Limit extreme exposure before execution.||shift(1)::At row t, show the signal that was known at t−1, not the signal computed at t.',params={'cap':[0.5,0.8,1.2]})
q(T,'stocks-categorical-onehot','Encode sector membership',4,'stocks','Return a one-hot Boolean DataFrame of sectors with columns sorted alphabetically.',
  'pd.get_dummies(df["sector"]).sort_index(axis=1)',
  'get_dummies::Convert one categorical sector per stock into indicator columns.||sort_index(axis=1)::Make the feature column order deterministic for downstream models.')
q(T,'panel-date-crosssection','Cross-sectional return rank matrix',4,'asset_panel','Rank returns by date, with rank 1 for the highest return, then pivot into dates × tickers.',
  'df.assign(rank=df.groupby("date")["ret"].rank(ascending=False, method="min")).pivot(index="date", columns="ticker", values="rank")',
  'groupby(date).rank::Rank within each date; larger returns receive smaller ranks.||assign::Attach ranks to the long panel without losing other columns.||pivot::Turn the normalized feature into a time-by-asset matrix.')

# 3: Time Series & Risk
T = 'Time Series & Risk'
q(T,'returns-rolling-vol','Rolling realized volatility',3,'returns','Return 5-session rolling sample volatility annualized by sqrt(252) for every asset.',
  'df.rolling(5).std() * np.sqrt(252)',
  'rolling(5).std()::For each asset and date, compute sample standard deviation over its trailing five observations.||sqrt(252)::Annualize the daily standard deviation assuming 252 trading days and square-root-of-time scaling.',ds={'kind':'returns','rows':18})
q(T,'returns-ewma-risk','EWMA risk monitor',4,'returns','Return exponentially weighted daily return volatility for all assets, with span {span} and adjust=False.',
  'df.ewm(span={span}, adjust=False).std()',
  'ewm(span={span})::Assign exponentially declining weight to older observations.||adjust=False::Use the recursive filter representation.||std()::Estimate exponentially weighted standard deviation for each asset.',params={'span':[4,6,8]},ds={'kind':'returns','rows':18})
q(T,'returns-pair-cov','Rolling pairwise covariance',4,'returns','Return a Series of 5-day rolling sample covariance between AAPL and MSFT.',
  'df["AAPL"].rolling(5).cov(df["MSFT"])',
  'df["AAPL"].rolling(5)::Create consecutive windows in AAPL returns.||cov(df["MSFT"])::Use MSFT over the aligned dates to obtain one covariance per window.',ds={'kind':'returns','rows':18})
q(T,'returns-beta','Rolling market beta',5,'returns','Calculate rolling 6-day beta of NVDA versus AAPL, as covariance divided by the rolling variance of AAPL.',
  'df["NVDA"].rolling(6).cov(df["AAPL"]) / df["AAPL"].rolling(6).var()',
  'rolling(6).cov::Estimate the rolling numerator Cov(NVDA,AAPL) using aligned windows.||rolling(6).var::Estimate Var(AAPL) over the same windows.||division::Beta is covariance with the benchmark divided by benchmark variance.',ds={'kind':'returns','rows':18})
q(T,'returns-cumulative-drawdown','Portfolio drawdown time series',4,'returns','Treat AAPL returns as strategy returns. Compute the drawdown Series from a compounded wealth index.',
  '(1 + df["AAPL"]).cumprod() / (1 + df["AAPL"]).cumprod().cummax() - 1',
  '(1+r).cumprod()::Compound each daily return into an evolving wealth index.||cummax()::Find the prior high-water mark of wealth at every date.||wealth / high - 1::Calculate the fractional loss from the historical peak.')
q(T,'returns-expanding-sharpe','Expanding Sharpe estimate',4,'returns','Return the expanding, annualized mean/std Sharpe ratio Series for AAPL, requiring at least four observations.',
  'df["AAPL"].expanding(min_periods=4).mean() / df["AAPL"].expanding(min_periods=4).std() * np.sqrt(252)',
  'expanding(min_periods=4)::Use every return seen up to each date, not a fixed lookback window.||mean / std::Form the running signal-to-noise ratio.||sqrt(252)::Annualize assuming daily returns and zero risk-free rate.',ds={'kind':'returns','rows':18})
q(T,'prices-pct-change','Last 10 trading-day returns',3,'price_panel','Forward-fill missing prices, calculate daily percentage returns without additional filling, and keep the last 10 rows.',
  'df.ffill().pct_change(fill_method=None).tail(10)',
  'ffill::Supply the last observed price where a quote is missing, an explicit causal policy.||pct_change(fill_method=None)::Convert sequential price differences into relative changes.||tail(10)::Restrict the view to recent dates.')
q(T,'returns-vwap-cov','Cross-asset sample covariance',3,'returns','Calculate the full sample covariance matrix for AAPL, MSFT and NVDA only, in that order.',
  'df[["AAPL", "MSFT", "NVDA"]].cov()',
  '[[...]]::Select assets and establish their column order.||cov()::Compute the sample covariance of selected asset returns across dates, yielding a square matrix.',ds={'kind':'returns','rows':18})
q(T,'returns-lagged-factor','Lagged cross-sectional factor',4,'returns','Return the cross-sectional mean return across all assets, lagged by one trading day.',
  'df.mean(axis=1).shift(1)',
  'mean(axis=1)::Collapse columns within each date to one market-wide cross-sectional return.||shift(1)::At date t, expose only the previous date’s computed factor.')
q(T,'prices-momentum','Causal momentum feature',4,'price_panel','Using forward-filled prices, return the 5-day price momentum matrix, lagged one day.',
  'df.ffill().pct_change(5, fill_method=None).shift(1)',
  'ffill::Make the explicit fill policy for intermittent missing prices.||pct_change(5)::Compute P_t/P_(t−5)−1 for each asset.||shift(1)::Delay every feature one session before it is used for trading.')
q(T,'returns-rolling-corr','Dynamic pairwise correlation',4,'returns','Return 6-day rolling correlation of NVDA and MSFT as a Series.',
  'df["NVDA"].rolling(6).corr(df["MSFT"])',
  'rolling(6)::Build six-session windows along dates.||corr(other)::Calculate Pearson correlation using the aligned second return Series for each window.',ds={'kind':'returns','rows':18})
q(T,'xi-net-pnl','Cost-adjusted P&L with latency',5,'xi_state','Return daily net strategy return using yesterday’s signal clipped to [-1,1] times today’s return, minus today’s cost.',
  'df["signal"].clip(-1, 1).shift(1) * df["ret"] - df["cost"]',
  'clip(-1,1).shift(1)::Bound the signal and delay exposure by one date; otherwise the backtest has look-ahead.||multiply by ret::Apply lagged position to the realized current return.||subtract cost::Account for transaction cost at the same date.')

# 4: Options and Dispersion
T = 'Options & Dispersion'
q(T,'opt-liquid-mid','Liquid option midquotes',3,'option_chain','Return expiry, strike, cp and midquote for options with bid > 0, ask > bid and volume >= {minvol}; sort by expiry and strike.',
  'df.loc[df["bid"].gt(0) & df["ask"].gt(df["bid"]) & df["volume"].ge({minvol})].assign(mid=lambda x: (x["bid"]+x["ask"])/2)[["expiry","strike","cp","mid"]].sort_values(["expiry","strike"])',
  'gt/ge masks::Reject non-positive bids, crossed markets, and inadequate volume using elementwise comparisons.||assign(mid=lambda x: ...)::Calculate midquotes from surviving rows, not unrelated data.||column selection + sort::Return a quote-ready table with consistent time/strike order.',params={'minvol':[20,70,130]})
q(T,'opt-spread-bps','Option spread in basis points',4,'option_chain','Create a Series of bid-ask spread divided by midpoint, expressed in basis points, for every option row.',
  '10000 * (df["ask"] - df["bid"]) / ((df["ask"] + df["bid"]) / 2)',
  'ask-bid::Compute absolute spread for every quote.||(ask+bid)/2::Compute mid price, the denominator.||10000*spread/mid::Convert relative spread into basis points for liquidity screening.')
q(T,'opt-iv-surface','Call implied-volatility surface',4,'option_chain','Return a matrix with expiry as rows, strike as columns and call IV as values, sorted by expiry and strike.',
  'df.query("cp == \'C\'").pivot(index="expiry", columns="strike", values="iv").sort_index().sort_index(axis=1)',
  'query(cp == C)::Exclude put observations before reshaping.||pivot(expiry,strike,iv)::Create a volatility surface from long option quotes; unique expiry/strike pairs are required.||sort_index on both axes::Guarantee consistent maturity and strike ordering.')
q(T,'opt-atm-chain','ATM volatility term structure',4,'option_chain','Return an expiry-indexed Series of ATM call IV at strike 100, sorted by expiry.',
  'df.loc[df["strike"].eq(100) & df["cp"].eq("C")].set_index("expiry")["iv"].sort_index()',
  'eq(100) & eq(C)::Select ATM strike and call contracts using two Boolean Series.||set_index("expiry")::Convert expiries to maturity labels.||["iv"].sort_index()::Extract the term structure as an ordered Series.')
q(T,'opt-straddle-premium','ATM straddle premium by expiry',4,'option_chain','Calculate call-plus-put ATM midpoint premium by expiry as a Series.',
  'df.loc[df["strike"].eq(100)].assign(mid=lambda x: (x["bid"]+x["ask"])/2).groupby("expiry")["mid"].sum()',
  'eq(100)::Keep ATM calls and puts and exclude other strikes.||assign(mid)::Calculate premium per instrument.||groupby(expiry).sum()::Combine the two legs of each same-expiry straddle.')
q(T,'opt-call-put-skew','Put-minus-call IV skew',5,'option_chain','Return put IV minus call IV at every (expiry,strike) pair as a Series with MultiIndex.',
  'df.pivot(index=["expiry","strike"], columns="cp", values="iv").eval("P - C")',
  'pivot(index=[expiry,strike])::Align put and call observations on EXACT maturity and strike keys.||eval("P - C")::Calculate skew on aligned columns without pairing quotes by arbitrary row position.')
q(T,'opt-vega-screen','Vega portfolio candidate screen',3,'option_chain','Return expiry, strike, cp, iv for contracts with absolute delta < {bound}, sorted by increasing IV.',
  'df.loc[df["delta"].abs().lt({bound}), ["expiry","strike","cp","iv"]].sort_values("iv")',
  'abs().lt({bound})::Select relatively delta-neutral option contracts; lt means strict less than.||loc::Return only the requested quote fields.||sort_values::Rank candidates by IV.',params={'bound':[0.45,0.60,0.75]})
q(T,'opt-volume-by-expiry','Options expiry liquidity',3,'option_chain','Return total option volume by expiry, sorted highest volume first.',
  'df.groupby("expiry")["volume"].sum().sort_values(ascending=False)',
  'groupby(expiry)::Aggregate all strikes and types sharing maturity.||sum()::Measure expiry-wide contract volume.||sort_values(ascending=False)::Prioritize the most liquid expiration.')
q(T,'disp-iv-gap','Index versus constituent IV gap',4,'dispersion','For each date, compute index IV minus the equal-weight average constituent IV (excluding INDEX). Return a date-indexed Series.',
  'df.query("symbol == \'INDEX\'").set_index("date")["iv"] - df.query("symbol != \'INDEX\'").groupby("date")["iv"].mean()',
  'query(index)::Take one index-IV quote per date.||query(not index).groupby(date).mean()::Average single-name IV quotes for the same dates.||Series subtraction::Align by date label; this is an IV gap, NOT implied-correlation estimation.')
q(T,'disp-vega-notional','Constituent vega totals',3,'dispersion','Return summed constituent vega by date, excluding INDEX, as a date-indexed Series.',
  'df.loc[df["symbol"].ne("INDEX")].groupby("date")["vega"].sum()',
  'ne("INDEX")::Keep all non-index option rows by label comparison.||groupby(date).sum()::Add constituent vegas within each observation date.')
q(T,'disp-weighted-iv','Synthetic constituent IV proxy',5,'dispersion','For each date, calculate the weighted mean constituent IV sum(weight*iv)/sum(weight), excluding INDEX. Return a Series.',
  'df.loc[df["symbol"].ne("INDEX")].assign(weighted_iv=lambda x: x["weight"]*x["iv"]).groupby("date")[["weighted_iv","weight"]].sum().eval("weighted_iv / weight")',
  'exclude INDEX::Only component options belong in the constituent proxy.||assign(weighted_iv)::Create weight-times-IV for each constituent and date.||groupby(date).sum()::Reduce numerator and denominator separately per day.||eval(division)::Form a weighted arithmetic-IV proxy; it is NOT a variance-consistent synthetic index IV.')
q(T,'disp-vega-delta-screen','Delta-near-neutral options',4,'dispersion','Keep constituent rows with absolute delta below {delta} and vega above {vega}; return date, symbol, delta, vega.',
  'df.loc[df["symbol"].ne("INDEX") & df["delta"].abs().lt({delta}) & df["vega"].gt({vega}), ["date","symbol","delta","vega"]]',
  'ne(index)::Exclude the index leg.||abs().lt / gt::Demand near-neutral delta and sufficiently large vega simultaneously.||loc::Select qualifying rows and explicitly requested columns.',params={'delta':[0.1,0.2,0.3],'vega':[35,60,90]})
q(T,'disp-iv-change','Daily index IV changes',4,'dispersion','Return first differences of INDEX implied volatility ordered by date.',
  'df.query("symbol == \'INDEX\'").set_index("date")["iv"].sort_index().diff()',
  'query + set_index::Isolate the index IV time series with date labels.||sort_index()::Ensure time order before differencing.||diff()::Compute IV_t-IV_(t−1) in decimal-volatility units.')

# 5: Market Microstructure
T = 'Market Microstructure'
q(T,'micro-quotes-mid','Executable quote midpoint',3,'market_events','Return symbol, time, and computed midpoint for quote events only, sorted by time.',
  'df.query("event == \'quote\'").assign(mid=lambda x: (x["bid"] + x["ask"])/2)[["symbol","time","mid"]].sort_values("time")',
  'query quote::Remove execution records, where bid/ask are absent.||assign mid::Vectorize the bid-ask midpoint calculation.||sort_values(time)::Preserve event chronology for later joins.')
q(T,'micro-trade-notional','Executed value by symbol',4,'market_events','Return total trade notional (trade_px × size) per symbol as a Series.',
  'df.query("event == \'trade\'").assign(notional=lambda x: x["trade_px"] * x["size"]).groupby("symbol")["notional"].sum()',
  'query trade::Use only actual executions.||assign notional::Calculate executed value for every record.||groupby(symbol).sum::Aggregate executed notional by ticker.')
q(T,'micro-asof-mid','Last quote before trade',5,'market_events','For each trade, attach the most recent quote midpoint for that ticker via backward as-of merge. Return symbol, time, trade_px, mid.',
  'pd.merge_asof(df.query("event == \'trade\'")[["time","symbol","trade_px"]].sort_values("time"), df.query("event == \'quote\'").assign(mid=lambda x: (x["bid"]+x["ask"])/2)[["time","symbol","mid"]].sort_values("time"), on="time", by="symbol", direction="backward")[["symbol","time","trade_px","mid"]]',
  'split trades / quotes::Create two relations from one event table.||sort_values(time)::Both as-of join inputs MUST be ordered by the matching time key.||merge_asof(...,by=symbol,direction=backward)::Find the latest quote known at or before each trade for the SAME ticker.||column projection::Return just trade and matched quote fields.')
q(T,'micro-effective-spread','Effective spread versus last quote',5,'market_events','For each trade, return 2 × absolute difference between trade price and previous same-ticker quote mid, as a Series indexed by trade time.',
  'pd.merge_asof(df.query("event == \'trade\'")[["time","symbol","trade_px"]].sort_values("time"), df.query("event == \'quote\'").assign(mid=lambda x: (x["bid"]+x["ask"])/2)[["time","symbol","mid"]].sort_values("time"), on="time", by="symbol", direction="backward").set_index("time").eval("2 * abs(trade_px - mid)")',
  'merge_asof backward::Align every execution with the latest earlier quote for its ticker rather than using future information.||set_index(time)::Give each output value a trade-time label.||eval(2 * abs(...))::Form a simple effective-spread proxy; no trade-sign inference is needed.')
q(T,'micro-volume-per-minute','Trade size by event minute',3,'market_events','Return total executed size by timestamp for trade events, sorted by time.',
  'df.query("event == \'trade\'").groupby("time")["size"].sum().sort_index()',
  'query::Exclude quote updates that have zero executed size.||groupby(time).sum::Add executions at identical timestamps, keeping a time-indexed Series.||sort_index::Order event times chronologically.')
q(T,'micro-symbol-vwap','Execution VWAP by ticker',5,'market_events','Return execution volume-weighted average price per ticker as a Series.',
  'df.query("event == \'trade\'").assign(notional=lambda x: x["trade_px"]*x["size"]).groupby("symbol")[["notional","size"]].sum().eval("notional / size")',
  'query trade::Exclude nonexecuted quotes.||assign(price*size)::Calculate dollar notional per execution.||groupby(symbol).sum()::Obtain total notional and volume per symbol.||eval(notional/size)::Divide after aggregation; averaging individual trade prices would be wrong.')

# 6: Regimes & Portfolio
T = 'Regimes & Portfolio'
q(T,'xi-stress-days','High-stress regime periods',3,'xi_state','Return ret, vol and p_stress for dates where the stress-regime probability is >= {prob}, ordered from most stressed to least.',
  'df.loc[df["p_stress"].ge({prob}), ["ret","vol","p_stress"]].sort_values("p_stress", ascending=False)',
  'ge({prob})::Mark dates with stress-regime probability at least the threshold.||loc::Retain the three relevant diagnostics.||sort_values::Show strongest stress evidence first.',params={'prob':[0.40,0.50,0.65]})
q(T,'xi-regime-entropy','Regime entropy indicator',4,'xi_state','Compute binary probability entropy -p*log(p)-(1-p)*log(1-p) as a Series for each date.',
  '-df["p_risk"]*np.log(df["p_risk"]) - df["p_stress"]*np.log(df["p_stress"])',
  'np.log(series)::Vectorize the log calculation over every date.||-p log p terms::Combine weighted uncertainty contributions for both regimes; larger entropy means a less decisive posterior.')
q(T,'xi-portfolio-weights','Volatility-scaled exposure',4,'xi_state','Return a Series of lagged signal clipped to [-1,1], divided by previous-day volatility, and then clipped to [-{cap}, {cap}].',
  '(df["signal"].shift(1).clip(-1,1) / df["vol"].shift(1)).clip(-{cap}, {cap})',
  'shift(1) on signal and vol::Only previous-date information is available for today’s weight.||clip(-1,1)::Bound the directional conviction before scaling.||divide by vol then clip::Apply inverse-risk scaling followed by a leverage limit.',params={'cap':[2,3,4]})
q(T,'xi-regime-switches','Regime classification changes',4,'xi_state','Return a Boolean Series identifying dates where the binary stress classification (p_stress > 0.5) changed versus the prior date.',
  'df["p_stress"].gt(0.5).ne(df["p_stress"].gt(0.5).shift(1))',
  'gt(0.5)::Create one Boolean regime state per date.||shift(1)::Align yesterday’s classification with today’s date.||ne::Mark changes; first row is True because previous state is missing.')
q(T,'xi-forecast-error','Out-of-sample forecast residuals',3,'xi_state','Return realized-minus-forecast errors only on dates with absolute error strictly above {threshold}.',
  '(df["ret"] - df["forecast"]).loc[lambda s: s.abs().gt({threshold})]',
  'ret - forecast::Construct the error series date by date with aligned indices.||abs().gt({threshold})::Mark unusually large misses by their magnitude, regardless of positive or negative sign.||loc[lambda s: ...]::Keep only those dates while preserving each error sign.',params={'threshold':[0.005,0.010,0.015]})
q(T,'xi-cumulative-alpha','Cumulative active return',4,'xi_state','Return compounded cumulative performance of the strategy minus compounded cumulative benchmark performance at each date.',
  '(1 + df["ret"]).cumprod() - (1 + df["benchmark"]).cumprod()',
  '(1+r).cumprod()::Construct one wealth curve for the strategy and another for the benchmark.||subtract wealth curves::Return the difference in cumulative total-return factors, not a cumulative sum of daily excess returns.')
q(T,'portfolio-holdings-pivot','Portfolio holdings matrix',3,'asset_panel','Return daily portfolio weight as a matrix of dates × tickers, with ticker columns ordered AAPL, JPM, MSFT, NVDA.',
  'df.pivot(index="date", columns="ticker", values="weight").reindex(columns=["AAPL","JPM","MSFT","NVDA"])',
  'pivot::Reshape long holdings into a 2D weight matrix: one observation per (date,ticker).||reindex(columns=...)::Fix ticker ordering for matrix multiplication and reporting.')
q(T,'portfolio-date-pnl','Daily weighted portfolio return',5,'asset_panel','Compute the cross-sectional weighted portfolio return per date using each asset weight × daily return. Return a date-indexed Series.',
  'df.assign(contribution=df["weight"]*df["ret"]).groupby("date")["contribution"].sum()',
  'assign(weight*return)::Calculate each asset contribution within its date.||groupby(date).sum()::Sum contributions to get one portfolio return per date. The weights in this dataset approximately sum to one per date.')
q(T,'portfolio-beta','Portfolio beta exposure',4,'asset_panel','For each date, calculate total portfolio beta as sum(weight × beta), returning a Series.',
  'df.assign(beta_contrib=df["weight"]*df["beta"]).groupby("date")["beta_contrib"].sum()',
  'assign(beta_contrib)::Translate holdings weights and individual beta values into contributions.||groupby(date).sum()::Aggregate one portfolio-level beta for each rebalance date.')
q(T,'portfolio-weight-turnover','One-way turnover by date',5,'asset_panel','Pivot holdings to dates × tickers, difference consecutive weight vectors, take absolute values, sum across tickers and divide by two. Return a date-indexed Series.',
  'df.pivot(index="date",columns="ticker",values="weight").diff().abs().sum(axis=1) / 2',
  'pivot::Place holdings into a consistent date-by-ticker matrix; alignment is by ticker label.||diff().abs()::Compute absolute changes in each asset weight from the prior rebalance.||sum(axis=1)/2::Aggregate rebalancing turnover across assets. The first row evaluates to zero under pandas sum defaults.')
q(T,'portfolio-concentration','Portfolio HHI',4,'asset_panel','For each date, compute portfolio concentration as sum of squared asset weights; return a Series.',
  'df.assign(weight_sq=df["weight"].pow(2)).groupby("date")["weight_sq"].sum()',
  'pow(2)::Square each asset weight independently.||groupby(date).sum()::Sum squared weights across the date’s holdings to obtain Herfindahl concentration.')
q(T,'portfolio-risk-sort','Rank names by risk contribution proxy',4,'asset_panel','Keep the top two tickers per date ranked by absolute weight × beta, returning date, ticker and a new risk_proxy column.',
  'df.assign(risk_proxy=(df["weight"]*df["beta"]).abs()).sort_values(["date","risk_proxy"],ascending=[True,False]).groupby("date",sort=False).head(2)[["date","ticker","risk_proxy"]]',
  'assign(weight*beta).abs::Define a simple absolute beta-exposure proxy for each holding.||sort by date and risk_proxy::Place largest exposures first within each date.||groupby(date).head(2)::Take two names per date rather than two overall.||project::Display only date, asset and exposure.')

# 7: MOT and Monte Carlo
T = 'MOT & Monte Carlo'
q(T,'mot-marginal-s0','Initial transport marginal',3,'mot_grid','Return the probability mass assigned to each initial support point s0, sorted ascending by s0.',
  'df.groupby("s0")["mass"].sum().sort_index()',
  'groupby(s0)::Collect transport couplings sharing the same first-period support point.||sum(mass)::Marginalize over all destination states s1.||sort_index::Put source support in increasing price order.')
q(T,'mot-marginal-s1','Terminal transport marginal',3,'mot_grid','Return terminal probability masses indexed by s1, sorted by increasing terminal support price.',
  'df.groupby("s1")["mass"].sum().sort_index()',
  'groupby(s1)::Collect all flows arriving at each terminal support price.||sum(mass)::Integrate out the source support s0.')
q(T,'mot-weighted-payoff','Transport-plan option price',4,'mot_grid','Return the scalar expected payoff under the joint transport mass.',
  '(df["mass"] * df["payoff"]).sum()',
  'mass*payoff::Weight each scenario payoff by joint probability of that source-destination pair.||sum()::Integrate over the discrete coupling to obtain the expected payoff.')
q(T,'mot-coupling-matrix','Coupling matrix',4,'mot_grid','Return a matrix with s0 as rows, s1 as columns and mass as each coupling cell, sorted on both support axes.',
  'df.pivot(index="s0",columns="s1",values="mass").sort_index().sort_index(axis=1)',
  'pivot::Turn long (source,destination,mass) records into a probability matrix.||sort_index on axes::Order both supports numerically; matrix row and column sums recover the marginals.')
q(T,'mot-conditional-target','Conditional terminal expectation',5,'mot_grid','For every s0, calculate E[S1 | S0=s0] under the (possibly nonmartingale) coupling as a Series.',
  'df.assign(mass_s1=df["mass"]*df["s1"]).groupby("s0")[["mass_s1","mass"]].sum().eval("mass_s1 / mass")',
  'assign(mass*s1)::Compute the weighted terminal contribution for every coupling cell.||groupby(s0).sum()::Create numerator and row-marginal denominator for each source support point.||eval(numerator/denominator)::Calculate conditional expectation. Compare with s0 to diagnose martingale violation.')
q(T,'mot-martingale-residual','Martingale constraint residual',5,'mot_grid','Return the weighted martingale residual per source support: sum(mass*(s1-s0)) grouped by s0.',
  'df.assign(residual=df["mass"] * (df["s1"]-df["s0"])).groupby("s0")["residual"].sum()',
  's1-s0::Compute the price change associated with each coupling pair.||multiply by mass::Weight each move by its joint probability.||groupby(s0).sum()::Check the martingale constraint for every initial support; target residual is zero in a true martingale coupling.')
q(T,'mot-total-negative-mass','Negative coupling diagnosis',3,'mot_grid','Return the scalar total magnitude of negative probability entries (should be zero for this valid synthetic mass).',
  'df["mass"].clip(upper=0).abs().sum()',
  'clip(upper=0)::Keep only negative values and replace positive masses by zero.||abs().sum()::Sum the magnitude of invalid negative probability, yielding a scalar diagnostic.')
q(T,'mot-normalized-price','Normalize expected transport payoff',4,'mot_grid','Return expected payoff per unit of total joint mass as a scalar, guarding against rounding of mass.',
  '(df["mass"] * df["payoff"]).sum() / df["mass"].sum()',
  'sum(mass*payoff)::Compute total probability-weighted payoff.||sum(mass)::Measure total stored mass, which can differ minutely from 1 after rounding.||divide::Return normalized expectation.')
q(T,'mc-terminal-gains','Monte Carlo terminal simple returns',3,'sim_paths','Return terminal price divided by initial price minus one, for each simulated path.',
  'arr[:, -1] / arr[:, 0] - 1',
  'arr[:,-1] and arr[:,0]::Extract terminal and starting price from every simulated path as two 1D vectors.||division -1::Calculate path-level simple total returns.')
q(T,'mc-path-drawdown','Per-path maximum drawdown',5,'sim_paths','Return the maximum drawdown per simulation path as a negative-valued 1D array.',
  '(arr / np.maximum.accumulate(arr, axis=1) - 1).min(axis=1)',
  'np.maximum.accumulate(axis=1)::Compute running peak within EACH simulated path, from left to right across time.||arr / peak - 1::Find drawdown at every path-time cell.||min(axis=1)::Take the worst drawdown for each path.')
q(T,'mc-asian-payoff','Arithmetic Asian call payoff',4,'sim_paths','For each simulated path, return max(average price across time - {strike}, 0) as a 1D array.',
  'np.maximum(arr.mean(axis=1) - {strike}, 0)',
  'mean(axis=1)::Collapse the time axis into one average price per simulated path.||subtract strike::Compute average-price intrinsic value.||maximum(...,0)::Apply the call option payoff floor.',params={'strike':[95,100,105]})
q(T,'mc-barrier-hit','Barrier first-passage indicator',4,'sim_paths','Return a Boolean vector indicating which simulated paths EVER traded at or above {barrier}.',
  'arr.ge({barrier})' if False else '(arr >= {barrier}).any(axis=1)',
  'arr >= barrier::Create a Boolean matrix showing when each path crosses the barrier.||any(axis=1)::Reduce across time, producing one Boolean flag per simulated path.',params={'barrier':[100,103,106]})
q(T,'mc-step-logreturns','Simulated log-return increments',4,'sim_paths','Return a matrix of adjacent log-price increments for all paths.',
  'np.diff(np.log(arr), axis=1)',
  'np.log(arr)::Convert simulated positive prices to log prices.||np.diff(axis=1)::Subtract adjacent time points within each path, yielding one fewer time column.')
q(T,'mc-quantile-wealth','Cross-path tail wealth',4,'sim_paths','Normalize every simulated path by its starting price, then return the 10th percentile normalized wealth at each time step.',
  'np.quantile(arr / arr[:, [0]], 0.1, axis=0)',
  'arr[:,[0]]::Extract the starting price of each path while retaining a second dimension for broadcasting.||arr / initial::Normalize path prices within each row, producing wealth starting at 1.||quantile(axis=0)::Collapse the path axis and return a 1D tail-wealth curve across time.')

# 8: Linear Algebra & Arrays
T = 'Linear Algebra & Arrays'
q(T,'la-correlation','Covariance to correlation',5,'risk_matrix','Convert the covariance matrix into a correlation matrix by dividing by pairwise standard deviations.',
  'arr / np.sqrt(np.outer(np.diag(arr), np.diag(arr)))',
  'diag(arr)::Extract asset variances from covariance diagonal.||outer(diag,diag)::For every asset pair multiply the two variances, forming a matrix.||sqrt and divide::Divide covariance_ij by sigma_i*sigma_j, giving 1 on the diagonal.')
q(T,'la-eigenvalues','Covariance eigenvalues',4,'risk_matrix','Return eigenvalues of the symmetric covariance matrix ordered largest to smallest.',
  'np.linalg.eigvalsh(arr)[::-1]',
  'eigvalsh::Use a symmetric-matrix eigensolver; the eigenvalues arrive sorted in ascending order.||[::-1]::Reverse the 1D eigenvalue vector to order principal risk directions from largest to smallest.')
q(T,'la-inverse-cov','Precision matrix',4,'risk_matrix','Compute the precision matrix by solving Sigma × X = Identity, rather than explicitly calling inv.',
  'np.linalg.solve(arr, np.eye(arr.shape[0]))',
  'eye(arr.shape[0])::Construct an identity right-hand side matching covariance dimension.||linalg.solve::Solve all columns simultaneously for X such that Sigma@X=I; often preferable to forming inv in production.')
q(T,'la-diagonal-risk','Volatility vector',3,'risk_matrix','Return a 1D vector of the standard deviations implied by the covariance matrix diagonal.',
  'np.sqrt(np.diag(arr))',
  'diag(arr)::Extract variances for each asset.||sqrt::Convert variance to standard deviation. The resulting vector has length equal to number of assets.')
q(T,'la-condition-number','Covariance conditioning',4,'risk_matrix','First convert covariance into correlation, then return the 2-norm condition number of the correlation matrix.',
  'np.linalg.cond(arr / np.sqrt(np.outer(np.diag(arr), np.diag(arr))))',
  'diag and outer::Convert asset variances into pairwise volatility products.||elementwise division::Normalize Sigma into an asset correlation matrix with ones on the diagonal.||linalg.cond::Measure numerical conditioning of the correlation matrix, relevant for stable inversion.')
q(T,'la-ols','Linear factor regression',5,'feature_matrix','Fit linear least-squares factor coefficients from columns 0–2 to target column 3, with no intercept. Return the coefficient vector.',
  'np.linalg.lstsq(arr[:, :3], arr[:, 3], rcond=None)[0]',
  'arr[:,:3]::Use the first three columns as the feature design matrix X.||arr[:,3]::Use the fourth column as the response vector y.||lstsq(X,y,rcond=None)[0]::Solve min squared residual norm of X beta - y and extract beta from the tuple returned by NumPy.')
q(T,'la-fitted-values','Regression fitted responses',5,'feature_matrix','Fit least-squares weights with the first three columns predicting the last column, then return all fitted y values.',
  'arr[:, :3] @ np.linalg.lstsq(arr[:, :3], arr[:, 3], rcond=None)[0]',
  'lstsq(X,y)[0]::Estimate the coefficient vector from the observed features and response.||X @ coefficients::Apply matrix multiplication to obtain a fitted value for each observation.')
q(T,'la-residual','Regression residual vector',5,'feature_matrix','Compute y minus fitted y for the three-factor least-squares model, as a 1D NumPy array.',
  'arr[:, 3] - arr[:, :3] @ np.linalg.lstsq(arr[:, :3], arr[:, 3], rcond=None)[0]',
  'lstsq(...)[0]::Fit the factor coefficients.||X @ beta::Generate in-sample fitted responses.||actual - fitted::Return regression residuals aligned with observations.')
q(T,'la-feature-standardize','Column-standardized features',4,'feature_matrix','Return all four columns standardized to mean 0 and population standard deviation 1.',
  '(arr - arr.mean(axis=0)) / arr.std(axis=0)',
  'mean/std(axis=0)::Compute one center and scale per feature column.||broadcast subtraction/division::Normalize every column independently; the output keeps the original matrix dimensions.')
q(T,'la-gram','Feature Gram matrix',4,'feature_matrix','Return X-transpose times X for the first three feature columns.',
  'arr[:, :3].T @ arr[:, :3]',
  'arr[:,:3]::Select X with n samples and 3 predictor columns.||.T @ X::Take the matrix product of transposed features with features, creating a 3-by-3 Gram matrix.')
q(T,'la-svd-components','Leading factor direction',5,'feature_matrix','Return the first right-singular vector of the centered first three feature columns.',
  'np.linalg.svd(arr[:, :3] - arr[:, :3].mean(axis=0), full_matrices=False)[2][0]',
  'center columns::Remove the mean from each predictor before PCA-like decomposition.||linalg.svd(...)[2]::Obtain V-transpose, whose rows are principal loading directions.||[0]::Select the leading right-singular vector; its sign is arbitrary in theory but deterministically fixed by the solver for this target.')
q(T,'la-row-norms','Path feature L2 norms',3,'feature_matrix','Return the Euclidean norm of the first three feature columns for each row.',
  'np.linalg.norm(arr[:, :3], axis=1)',
  'arr[:,:3]::Take three coordinates for every observation.||norm(axis=1)::Compute sqrt(sum(x_i²)) within each row, obtaining one norm per observation.')
q(T,'la-einsum-cov','Quadratic covariance contraction',5,'risk_matrix','For an equal-weight vector across assets, return its covariance quadratic form wᵀΣw as a scalar using einsum.',
  'np.einsum("i,ij,j->", np.ones(arr.shape[0])/arr.shape[0], arr, np.ones(arr.shape[0])/arr.shape[0])',
  'ones(n)/n::Create equal portfolio weights across all n assets.||einsum("i,ij,j->")::Contract two weight vectors with the covariance matrix; output is a scalar portfolio variance.')

# Additional integrated workflows: merging, reshaping, causal alignment, and linear algebra
T = 'Data Cleaning & Alignment'
q(T,'asset-merge-metadata','Join asset volume to ticker metadata',4,'asset_panel','Build one row per ticker with its sector and total traded volume, indexed and sorted by ticker.',
  'df[["ticker","sector"]].drop_duplicates().merge(df.groupby("ticker",as_index=False)["volume"].sum(),on="ticker",validate="one_to_one").set_index("ticker").sort_index()',
  'drop_duplicates::Build a unique ticker-to-sector metadata table.||groupby + sum::Build a second table of total asset volumes.||merge(...,validate=one_to_one)::Join two unique key tables; validate prevents accidental row multiplication.||set_index::Use ticker labels as the final semantic index.')
q(T,'price-pair-fallback','Fallback quote source',4,'price_panel','For each date, return MSFT price if present, otherwise AAPL price, as a date-indexed Series.',
  'df["MSFT"].combine_first(df["AAPL"])',
  'combine_first::Keep primary MSFT quotes unless missing, then take the aligned AAPL value as fallback.||alignment::Series are matched by date index, NOT by bare array position.')
q(T,'panel-reshape-melt','Convert returns matrix to long panel',4,'returns','Transform date-indexed asset return matrix into a long DataFrame with date, ticker and ret columns.',
  'df.reset_index().melt(id_vars="date",var_name="ticker",value_name="ret")',
  'reset_index::Restore date as a normal column rather than an index label.||melt(id_vars=date)::Unpivot four asset columns into ticker labels and ret values, yielding one row per date/asset pair.')
q(T,'panel-unstack-returns','Stack/unstack round trip',4,'returns','Stack the return matrix into a date-and-ticker MultiIndex Series and unstack it back into a DataFrame with original column order.',
  'df.stack().unstack()',
  'stack::Move the asset column axis into a second level of the row index.||unstack::Move that ticker index level back into columns; the result is again a date-by-asset DataFrame.')
T = 'Feature Engineering'
q(T,'panel-market-neutral-score','Rank normalized daily signals',5,'asset_panel','Within each date, calculate demeaned returns and then rank them descending within date as a Series, with rank 1 best.',
  '(df["ret"] - df.groupby("date")["ret"].transform("mean")).groupby(df["date"]).rank(ascending=False, method="min")',
  'transform(mean)::Demean returns independently for each trading day, preserving original row alignment.||groupby(df[date]).rank::Rank the cross-sectional residuals within their own date, not globally.')
q(T,'panel-trade-sector-filter','Sector-neutral liquidity filter',5,'asset_panel','Return ticker, date, ret, volume for Tech-sector records with volume above their SAME-DATE sector average.',
  'df.loc[df["sector"].eq("Tech") & df["volume"].gt(df.groupby(["date","sector"])["volume"].transform("mean")), ["ticker","date","ret","volume"]]',
  'groupby([date,sector]).transform(mean)::Compute a sector-relative daily volume benchmark aligned with every observation.||eq(Tech) & gt(mean)::Require Tech classification and unusually high volume together.||loc projection::Return only selected trade candidate fields.')
T = 'Time Series & Risk'
q(T,'monthly-terminal-price','Month-end price resampling',4,'price_panel','Forward-fill missing prices, resample to business month-end using the final available observation, then return the resulting matrix.',
  'df.ffill().resample("BME").last()',
  'ffill::Apply an explicitly causal missing-price policy.||resample("BME").last()::Group daily prices by business month-end periods and select the last available price per asset.')
q(T,'price-stale-gap-age','Detect stale price locations',4,'price_panel','Return a Boolean matrix showing where a price is absent, including all assets and dates.',
  'df.isna() & df.ffill().notna()',
  'isna::Find actual missing quotes.||ffill().notna::Ensure a prior value exists that could be carried forward.||&::Mark missing quotes that are forward-fillable, not initial missing values.')
T = 'Options & Dispersion'
q(T,'option-days-to-expiry','Option maturity clock',4,'option_chain','Return a Series containing number of calendar days between each expiry and 2026-11-04.',
  '(df["expiry"] - pd.Timestamp("2026-11-04")).dt.days',
  'expiry - Timestamp::Create a vector of time deltas, one per option record.||dt.days::Extract integer calendar days; no year-fraction convention is implied.')
q(T,'disp-relative-vega','Vega share by session',4,'dispersion','Return each constituent option vega as a fraction of total constituent vega for its date; index must retain original row numbers.',
  'df.loc[df["symbol"].ne("INDEX"), "vega"] / df.loc[df["symbol"].ne("INDEX")].groupby("date")["vega"].transform("sum")',
  'ne(INDEX)::Exclude index-option exposure from both numerator and denominator.||groupby(date).transform(sum)::Repeat same-day constituent vega total at each relevant row.||division::Calculate each component share with original row index alignment.')
T = 'MOT & Monte Carlo'
q(T,'mc-trapezoid-asian','Trapezoidal path-average payoff',5,'sim_paths','For each path, compute the time average by trapezoidal integration over equally spaced steps, then return max(average-100,0).',
  'np.maximum((arr[:, :-1]+arr[:, 1:]).sum(axis=1)/(2*(arr.shape[1]-1))-100,0)',
  'arr[:,:-1] + arr[:,1:]::Pair each adjacent price on every path; this creates trapezoid endpoint sums.||sum(axis=1)/(2*(T-1))::Compute equal-time-step trapezoidal average over all intervals, with endpoint weights half of interior weights.||maximum(...-100,0)::Apply the arithmetic Asian call payoff.')
q(T,'mot-support-probability','Conditional probability matrix',5,'mot_grid','Return the transport coupling probability matrix normalized by each source-state row marginal, indexed by source and terminal supports.',
  'df.pivot(index="s0",columns="s1",values="mass").pipe(lambda x: x.div(x.sum(axis=1),axis=0))',
  'pivot::Turn coupling records into source-by-destination joint mass.||sum(axis=1)::Compute each source marginal probability.||div(...,axis=0)::Divide each row by its own marginal to get conditional terminal probabilities; each row sums to 1.')
T = 'Linear Algebra & Arrays'
q(T,'la-cholesky-factor','Covariance Cholesky factor',4,'risk_matrix','Normalize covariance to correlation, then return its lower-triangular Cholesky factor.',
  'np.linalg.cholesky(arr / np.sqrt(np.outer(np.diag(arr), np.diag(arr))))',
  'diag and outer::Build all sigma_i*sigma_j products from diagonal covariance entries.||divide::Form the correlation matrix by normalizing covariance values.||linalg.cholesky::Factor the positive definite correlation matrix as L@L.T, useful for correlated Monte Carlo shocks.')
q(T,'la-batched-take','Find largest feature magnitude',5,'feature_matrix','For every row, return the value from columns 0–2 having the largest absolute magnitude, preserving the sign as a 1D array.',
  'np.take_along_axis(arr[:, :3], np.abs(arr[:, :3]).argmax(axis=1, keepdims=True), axis=1).ravel()',
  'abs(...).argmax(axis=1,keepdims=True)::Find the column POSITION of largest absolute feature per row; shape is (n,1).||take_along_axis::Gather the ORIGINAL signed value at each row-specific position.||ravel()::Flatten the n-by-1 result to the requested n-element vector.')

# Persist one JSON per topic. Files remain independently hand-editable.
existing_ids = set()
for track, exercises in packs.items():
    for row in exercises:
        assert row['id'] not in existing_ids, f'Duplicate exercise ID: {row["id"]}'
        existing_ids.add(row['id'])
        assert 1 <= row['difficulty'] <= 5
        assert row['explanation'] and all(s['code'] and s['meaning'] for s in row['explanation'])
        for k, value in row.get('parameters', {}).items():
            mapping = {n: p['choices'][0] for n, p in row['parameters'].items()}
            for part in [row['reference'], row['instructions'], row['hint'], *[s['code'] for s in row['explanation']], *[s['meaning'] for s in row['explanation']]]:
                part.format_map(mapping)
    name = 'quant_' + track.lower().replace(' & ', '_').replace(' ', '_') + '.json'
    path = ROOT / 'exercise_packs' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and '--force' not in sys.argv:
        print(f'{name}: exists already; keeping your edits (use --force to regenerate)')
        continue
    path.write_text(json.dumps(exercises, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'{name}: {len(exercises)} tasks')
print(f'Created {len(existing_ids)} advanced exercises in {len(packs)} editable packs. Core library untouched.')
