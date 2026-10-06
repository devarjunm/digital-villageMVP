import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/markets.dart';
import '../../widgets/common.dart';

/// Market prices, arrivals and the price outlook.
///
/// Three tabs, all fed by real endpoints. The price rows keep their provider,
/// retrieval time and source link; the estimate tab shows the trend chart with
/// observed and estimated points drawn differently, and says "no estimate
/// available" when the model has none, instead of filling the gap.
class MarketsScreen extends StatefulWidget {
  const MarketsScreen({super.key});

  @override
  State<MarketsScreen> createState() => _MarketsScreenState();
}

class _MarketsScreenState extends State<MarketsScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs = TabController(length: 3, vsync: this);

  List<MarketCrop> _crops = const [];
  bool _busy = false;
  String? _error;
  MarketPricePage? _prices;
  ArrivalsPage? _arrivals;
  String? _crop;
  String? _market;
  String? _state;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _bootstrap());
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final crops = await context.repos.markets.crops();
      if (!mounted) return;
      setState(() {
        _crops = crops;
        _crop = crops.isNotEmpty ? crops.first.cropCode : 'onion';
      });
      await _load();
    } on ApiException catch (error) {
      setState(() {
        _busy = false;
        _error = error.userMessage;
      });
    }
  }

  Future<void> _load() async {
    final repos = context.repos;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final prices = await repos.markets.prices(
        crop: _crop,
        market: _market,
        state: _state,
      );
      final arrivals = await repos.markets.arrivals(
        crop: _crop,
        market: _market,
        state: _state,
      );
      if (!mounted) return;
      setState(() {
        _prices = prices;
        _arrivals = arrivals;
        _busy = false;
      });
    } on ApiException catch (error) {
      setState(() {
        _busy = false;
        _error = error.userMessage;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('markets_title')),
        bottom: TabBar(
          controller: _tabs,
          tabs: [
            Tab(text: context.t('prices')),
            Tab(text: context.t('arrivals')),
            Tab(text: context.t('price_intelligence')),
          ],
        ),
        actions: [
          IconButton(
            tooltip: context.t('refresh'),
            icon: const Icon(Icons.refresh),
            onPressed: _busy ? null : _load,
          ),
        ],
      ),
      body: Column(
        children: [
          _FilterBar(
            crops: _crops,
            crop: _crop,
            onCropChanged: (value) {
              setState(() => _crop = value);
              _load();
            },
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.all(16),
              child: ErrorState(message: _error!, onRetry: _load),
            ),
          if (_busy)
            const Padding(padding: EdgeInsets.all(20), child: LoadingState()),
          Expanded(
            child: TabBarView(
              controller: _tabs,
              children: [
                _PricesTab(page: _prices),
                _ArrivalsTab(page: _arrivals),
                _EstimateTab(cropCode: _crop, marketCode: _market),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _FilterBar extends StatelessWidget {
  const _FilterBar(
      {required this.crops, required this.crop, required this.onCropChanged});

  final List<MarketCrop> crops;
  final String? crop;
  final ValueChanged<String?> onCropChanged;

  @override
  Widget build(BuildContext context) {
    if (crops.isEmpty) return const SizedBox.shrink();
    return SizedBox(
      height: 46,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        children: crops
            .map(
              (item) => Padding(
                padding: const EdgeInsets.only(right: 8),
                child: FilterChip(
                  label: Text(item.name),
                  avatar: item.hasDemoPrices
                      ? const Icon(Icons.science_outlined, size: 14)
                      : null,
                  selected: crop == item.cropCode,
                  onSelected: (_) => onCropChanged(item.cropCode),
                ),
              ),
            )
            .toList(),
      ),
    );
  }
}

class _PricesTab extends StatelessWidget {
  const _PricesTab({required this.page});

  final MarketPricePage? page;

  @override
  Widget build(BuildContext context) {
    final data = page;
    if (data == null) return const SizedBox.shrink();
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
      children: [
        Row(
          children: [
            DataClassChip(value: data.isDemo ? 'estimate' : 'observed'),
            const SizedBox(width: 8),
            if (data.isDemo) DemoChip(notice: data.notices.join(' ')),
            const Spacer(),
            Text(
              Fmt.relative(data.retrievedAt,
                  language: context.session.languageCode),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          '${context.t('market_provider')}: ${data.provider} · ${data.count} rows',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (data.notices.isNotEmpty) ...[
          const SizedBox(height: 10),
          Notice(
            kind: data.isDemo ? NoticeKind.demo : NoticeKind.info,
            message: data.notices.first,
            items: data.notices.length > 1 ? data.notices.sublist(1) : const [],
          ),
        ],
        if (data.disclaimer.isNotEmpty) ...[
          const SizedBox(height: 10),
          Notice(kind: NoticeKind.warning, message: data.disclaimer),
        ],
        const SizedBox(height: 12),
        if (data.items.isEmpty)
          EmptyState(title: context.t('no_prices'))
        else
          ...data.items.map((price) => _PriceCard(price: price)),
      ],
    );
  }
}

class _PriceCard extends StatelessWidget {
  const _PriceCard({required this.price});

  final MarketPrice price;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      price.marketName,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                  ),
                  if (price.isEstimate) const MetaPill(text: 'estimate'),
                  Text(
                    Fmt.date(price.priceDate,
                        language: context.session.languageCode),
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
              const SizedBox(height: 2),
              Text(
                [price.cropName, price.district, price.state]
                    .whereType<String>()
                    .where((value) => value.isNotEmpty)
                    .join(' · '),
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: StatTile(
                      label: context.t('modal_price'),
                      value: Fmt.inr(price.modalPrice),
                      hint: price.unit,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: StatTile(
                      label: context.t('min_price'),
                      value: Fmt.inr(price.minPrice),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: StatTile(
                      label: context.t('max_price'),
                      value: Fmt.inr(price.maxPrice),
                    ),
                  ),
                ],
              ),
              if (price.arrivalsTonnes != null) ...[
                const SizedBox(height: 8),
                Text(
                  '${context.t('arrivals_tonnes')}: ${Fmt.number(price.arrivalsTonnes, decimals: 1)} t',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
              if (price.sourceUrl != null) ...[
                const SizedBox(height: 4),
                SourceLine(
                    title: price.source ?? context.t('source'),
                    url: price.sourceUrl),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _ArrivalsTab extends StatelessWidget {
  const _ArrivalsTab({required this.page});

  final ArrivalsPage? page;

  @override
  Widget build(BuildContext context) {
    final data = page;
    if (data == null) return const SizedBox.shrink();
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
      children: [
        Row(
          children: [
            if (data.isDemo) DemoChip(notice: data.notices.join(' ')),
            const Spacer(),
            Text(
              '${context.t('market_provider')}: ${data.provider}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
        if (data.note != null) ...[
          const SizedBox(height: 10),
          Notice(kind: NoticeKind.info, message: data.note!),
        ],
        if (data.notices.isNotEmpty) ...[
          const SizedBox(height: 10),
          Notice(kind: NoticeKind.info, message: data.notices.join('\n')),
        ],
        const SizedBox(height: 12),
        if (data.rows.isEmpty)
          EmptyState(title: context.t('no_prices'))
        else
          Card(
            child: Column(
              children: [
                for (final row in data.rows)
                  ListTile(
                    dense: true,
                    title: Text(row.marketName ?? '—'),
                    subtitle: Text(
                      [
                        row.cropName ?? '',
                        if (row.date != null)
                          Fmt.date(row.date,
                              language: context.session.languageCode),
                      ].where((value) => value.isNotEmpty).join(' · '),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    trailing: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        if (row.arrivalsTonnes != null)
                          Text(
                              '${Fmt.number(row.arrivalsTonnes, decimals: 1)} t'),
                        if (row.modalPrice != null)
                          Text(
                            Fmt.pricePerUnit(row.modalPrice, row.unit),
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        if (row.isEstimate)
                          Text(
                            context.t('estimated'),
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

/// Observed history plus the model's outlook, drawn on one chart with estimates
/// distinguished from recorded prices.
class _EstimateTab extends StatefulWidget {
  const _EstimateTab({required this.cropCode, this.marketCode});

  final String? cropCode;
  final String? marketCode;

  @override
  State<_EstimateTab> createState() => _EstimateTabState();
}

class _EstimateTabState extends State<_EstimateTab> {
  int _days = 30;
  bool _busy = false;
  String? _error;
  PriceTrend? _trend;
  PriceEstimate? _estimate;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void didUpdateWidget(covariant _EstimateTab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.cropCode != oldWidget.cropCode) _load();
  }

  Future<void> _load() async {
    final crop = widget.cropCode;
    if (crop == null) return;
    final repos = context.repos;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final trend = await repos.markets.trend(
        crop: crop,
        market: widget.marketCode,
        days: _days,
      );
      PriceEstimate? estimate;
      try {
        estimate = await repos.markets.estimate(
          crop: crop,
          market: widget.marketCode,
          horizonDays: 7,
        );
      } on ApiException {
        estimate = null;
      }
      if (!mounted) return;
      setState(() {
        _trend = trend;
        _estimate = estimate;
        _busy = false;
      });
    } on ApiException catch (error) {
      setState(() {
        _busy = false;
        _error = error.userMessage;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final trend = _trend;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
      children: [
        Row(
          children: [
            Chip(
              label: Text('${_days}d'),
              onDeleted: null,
            ),
            const SizedBox(width: 8),
            ...([7, 30, 90].map(
              (days) => Padding(
                padding: const EdgeInsets.only(right: 6),
                child: ChoiceChip(
                  label: Text('${days}d'),
                  selected: _days == days,
                  onSelected: (_) {
                    setState(() => _days = days);
                    _load();
                  },
                ),
              ),
            )),
          ],
        ),
        if (_busy)
          const Padding(padding: EdgeInsets.all(20), child: LoadingState()),
        if (_error != null) ErrorState(message: _error!, onRetry: _load),
        if (trend != null && !_busy) ...[
          SectionCard(
            title: context.t('price_trend'),
            subtitle: '${trend.cropCode} · ${trend.unit}',
            trailing: MetaPill(
              text: Fmt.humanize(trend.direction),
              color: switch (trend.direction) {
                'rising' => const Color(0xFF1F6F3F),
                'falling' => const Color(0xFFB3261E),
                _ => null,
              },
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (trend.changePercent != null)
                  Text(
                    '${context.t('change_percent')}: ${Fmt.percent(trend.changePercent)}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                const SizedBox(height: 8),
                PriceSparkline(
                  values:
                      trend.points.map((point) => point.modalPrice).toList(),
                  labels: trend.points
                      .map(
                        (point) => point.priceDate == null
                            ? ''
                            : '${point.priceDate!.day}/${point.priceDate!.month}',
                      )
                      .toList(),
                ),
                const SizedBox(height: 6),
                Text(
                  context.t('estimate_points_note'),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                if (trend.methodNote != null) ...[
                  const SizedBox(height: 6),
                  Text(
                    '${context.t('method_note')}: ${trend.methodNote}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
                if (trend.isDemo) ...[
                  const SizedBox(height: 8),
                  DemoChip(notice: trend.notices.join(' ')),
                ],
              ],
            ),
          ),
          const SizedBox(height: 14),
        ],
        SectionCard(
          title: context.t('price_intelligence'),
          child: _estimate == null
              ? Text(
                  context.t('not_available'),
                  style: Theme.of(context).textTheme.bodySmall,
                )
              : !_estimate!.available
                  ? Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Notice(
                          kind: NoticeKind.warning,
                          title: context.t('estimate_unavailable'),
                          message: _estimate!.reason ??
                              'The price model has no outlook for this crop and market.',
                        ),
                        const SizedBox(height: 8),
                        Text(
                          _estimate!.confidenceInterpretation,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    )
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${context.t('horizon_days')}: ${_estimate!.horizonDays}',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                        const SizedBox(height: 8),
                        ..._estimate!.points.map(
                          (point) => InfoRow(
                            label: 'D+${point.dayOffset}',
                            value: point.estimatedPrice == null
                                ? '—'
                                : Fmt.pricePerUnit(
                                    point.estimatedPrice,
                                    _estimate!.unit,
                                  ),
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          _estimate!.confidenceInterpretation,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                        if (_estimate!.modelName != null)
                          InfoRow(
                              label: context.t('model_used'),
                              value: _estimate!.modelName!),
                        if (_estimate!.modelVersion != null)
                          InfoRow(
                              label: context.t('model_version'),
                              value: _estimate!.modelVersion!),
                        const SizedBox(height: 8),
                        Notice(
                            kind: NoticeKind.ai,
                            message: _estimate!.disclaimer),
                      ],
                    ),
        ),
      ],
    );
  }
}
