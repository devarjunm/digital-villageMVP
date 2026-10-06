import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/farm.dart';
import '../../models/weather.dart';
import '../../widgets/common.dart';

/// Weather for a location or a farm.
///
/// Location resolution order: the farm passed in by the caller, then the saved
/// profile coordinates. If neither exists the screen says so and offers the farm
/// list, instead of silently querying a default city. The provider name, the
/// observation time and the demo flag come straight from the API response.
class WeatherScreen extends StatefulWidget {
  const WeatherScreen({super.key});

  @override
  State<WeatherScreen> createState() => _WeatherScreenState();
}

class _WeatherScreenState extends State<WeatherScreen> {
  int _tick = 0;
  String? _farmId;
  List<Farm> _farms = const [];
  double? _latitude;
  double? _longitude;
  String _place = '';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _resolveLocation());
  }

  Future<void> _resolveLocation() async {
    final arguments = ModalRoute.of(context)?.settings.arguments;
    final session = context.session;
    final repos = context.repos;
    try {
      if (session.isSignedIn) {
        final farms = await repos.farms.list();
        final profile = session.profile ?? await repos.farmer.me();
        if (!mounted) return;
        String? farmId;
        if (arguments is Map && arguments['farmId'] is String) {
          farmId = arguments['farmId'] as String;
        }
        final selected = farms.where((farm) => farm.id == farmId).firstOrNull;
        setState(() {
          _farms = farms;
          _farmId = selected?.id;
          _latitude = selected?.latitude ?? profile.latitude;
          _longitude = selected?.longitude ?? profile.longitude;
          _place = selected?.placeLabel ?? profile.placeLabel;
          _tick++;
        });
      } else {
        if (mounted) setState(() => _tick++);
      }
    } on ApiException {
      if (mounted) setState(() => _tick++);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('weather_title')),
        actions: [
          IconButton(
            tooltip: context.t('refresh'),
            icon: const Icon(Icons.refresh),
            onPressed: () => setState(() => _tick++),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          if (_farms.isNotEmpty)
            DropdownField<String>(
              label: context.t('use_farm_location'),
              value: _farmId,
              items: _farms.map((farm) => farm.id).toList(),
              labelBuilder: (id) =>
                  _farms.firstWhere((farm) => farm.id == id).name,
              onChanged: (value) {
                final farm = value == null
                    ? null
                    : _farms.firstWhere((item) => item.id == value);
                setState(() {
                  _farmId = value;
                  if (farm != null) {
                    _latitude = farm.latitude;
                    _longitude = farm.longitude;
                    _place = farm.placeLabel;
                  }
                  _tick++;
                });
              },
            ),
          if (_latitude == null && _longitude == null) ...[
            Notice(
              kind: NoticeKind.warning,
              title: context.t('no_location_note'),
              message:
                  'The backend can still answer for a default region, but a weather value for a '
                  'place you do not farm would be misleading, so no query is made here.',
              items: const [],
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: () => Navigator.of(context).pushNamed(Routes.farms),
              icon: const Icon(Icons.add_location_alt_outlined, size: 18),
              label: Text(context.t('my_farms')),
            ),
          ] else ...[
            AsyncSection<WeatherNow>(
              refreshTick: _tick,
              load: () => context.repos.weather.current(
                latitude: _latitude,
                longitude: _longitude,
              ),
              builder: (context, weather, reload) => _CurrentWeatherCard(
                weather: weather,
                place: _place,
              ),
            ),
            const SizedBox(height: 14),
            AsyncSection<WeatherForecast>(
              refreshTick: _tick,
              load: () => context.repos.weather.forecast(
                latitude: _latitude,
                longitude: _longitude,
                days: 5,
              ),
              builder: (context, forecast, reload) =>
                  _ForecastCard(forecast: forecast),
            ),
            const SizedBox(height: 14),
            AsyncSection<List<WeatherAlert>>(
              refreshTick: _tick,
              load: () => context.repos.weather.alerts(
                latitude: _latitude,
                longitude: _longitude,
              ),
              isEmpty: (alerts) => alerts.isEmpty,
              emptyBuilder: (context, reload) => SectionCard(
                title: context.t('alerts'),
                child: Text(
                  context.t('no_alerts'),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
              builder: (context, alerts, reload) => SectionCard(
                title: context.t('alerts'),
                child: Column(
                  children: alerts
                      .map(
                        (alert) => Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Notice(
                            kind: alert.severity.toLowerCase() == 'severe'
                                ? NoticeKind.danger
                                : NoticeKind.warning,
                            title: '${alert.event} · ${alert.severity}',
                            message: alert.description ?? alert.headline,
                            items: [
                              if (alert.instruction != null) alert.instruction!,
                              if (alert.validTo != null)
                                'Valid until ${Fmt.dateTime(alert.validTo, language: context.session.languageCode)}',
                            ],
                          ),
                        ),
                      )
                      .toList(),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _CurrentWeatherCard extends StatelessWidget {
  const _CurrentWeatherCard({required this.weather, required this.place});

  final WeatherNow weather;
  final String place;

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: context.t('current_weather'),
      subtitle: place.isEmpty ? null : place,
      trailing: weather.isDemo ? DemoChip(notice: weather.demoNotice) : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                Fmt.temp(weather.temperatureC),
                style: Theme.of(context).textTheme.displaySmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text(
                    weather.conditionText ??
                        Fmt.humanize(weather.conditionCode),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 16,
            runSpacing: 8,
            children: [
              _Metric(
                  label: context.t('feels_like'),
                  value: Fmt.temp(weather.feelsLikeC)),
              _Metric(
                label: context.t('humidity'),
                value: Fmt.percent(weather.humidityPercent, decimals: 0),
              ),
              _Metric(
                  label: context.t('rainfall'),
                  value: Fmt.mm(weather.rainfallMm)),
              _Metric(
                  label: context.t('wind'),
                  value: Fmt.wind(weather.windSpeedKmh)),
              if (weather.pressureHpa != null)
                _Metric(
                    label: context.t('pressure'),
                    value: '${weather.pressureHpa!.toStringAsFixed(0)} hPa'),
            ],
          ),
          if (weather.farmingNote != null) ...[
            const SizedBox(height: 12),
            Notice(kind: NoticeKind.info, message: weather.farmingNote!),
          ],
          if (weather.demoNotice != null && !weather.isDemo) ...[
            const SizedBox(height: 10),
            Notice(kind: NoticeKind.info, message: weather.demoNotice!),
          ],
          const SizedBox(height: 12),
          Text(
            [
              '${context.t('weather_provider')}: ${weather.provider}',
              if (weather.source != null) weather.source!,
              '${context.t('observed_at')}: '
                  '${Fmt.dateTime(weather.observedAt, language: context.session.languageCode)}',
              if (weather.cached) 'cached',
              if (weather.dataClass != null) Fmt.humanize(weather.dataClass!),
            ].join(' · '),
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ],
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
        ),
        Text(value, style: Theme.of(context).textTheme.bodyMedium),
      ],
    );
  }
}

class _ForecastCard extends StatelessWidget {
  const _ForecastCard({required this.forecast});

  final WeatherForecast forecast;

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: context.t('forecast'),
      trailing: forecast.isDemo ? DemoChip(notice: forecast.demoNotice) : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ...forecast.days.map(
            (day) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 84,
                    child: Text(
                      Fmt.weekdayShort(day.forecastFor,
                          language: context.session.languageCode),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          day.conditionText ?? Fmt.humanize(day.conditionCode),
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                        if (day.rainfallProbabilityPercent != null)
                          Text(
                            '${Fmt.percent(day.rainfallProbabilityPercent, decimals: 0)} '
                            '${context.t('rain_probability')}',
                            style:
                                Theme.of(context).textTheme.bodySmall?.copyWith(
                                      color: Theme.of(context)
                                          .colorScheme
                                          .onSurfaceVariant,
                                    ),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    '${Fmt.degrees(day.tempMinC)} / ${Fmt.degrees(day.tempMaxC)}',
                    style: Theme.of(context).textTheme.bodySmall,
                    textAlign: TextAlign.right,
                  ),
                ],
              ),
            ),
          ),
          if (forecast.advisories.isNotEmpty) ...[
            const Divider(height: 24),
            // Wrap rather than Row: the label is translated, and a longer
            // Marathi or Hindi label must not overflow the card.
            Wrap(
              spacing: 8,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(context.t('advisories'),
                    style: Theme.of(context).textTheme.labelLarge),
                DataClassChip(value: forecast.advisoriesDataClass),
              ],
            ),
            const SizedBox(height: 6),
            ...forecast.advisories.map(
              (advisory) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('• '),
                    Expanded(
                      child: Text(advisory,
                          style: Theme.of(context).textTheme.bodySmall),
                    ),
                  ],
                ),
              ),
            ),
          ],
          const SizedBox(height: 8),
          Text(
            [
              '${context.t('weather_provider')}: ${forecast.provider}',
              if (forecast.source != null) forecast.source!,
              if (forecast.isDemo) context.t('demo_data'),
            ].join(' · '),
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ],
      ),
    );
  }
}
