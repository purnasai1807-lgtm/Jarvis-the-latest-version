import 'package:flutter_test/flutter_test.dart';

import 'package:jarvis_mobile/main.dart';

void main() {
  testWidgets('shows setup on first launch', (WidgetTester tester) async {
    await tester.pumpWidget(const JarvisApp(hasCredentials: false));
    expect(find.text('Connect to your PC'), findsOneWidget);
  });
}
