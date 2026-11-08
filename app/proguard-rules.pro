# Keep the wire-format classes readable in crash reports. When a user reports
# "it stopped warning me about obstacles", the sensor frame fields are the first
# thing you need to see.
-keep class bd.visionassistant.protocol.** { *; }
-keep class bd.visionassistant.core.** { *; }
