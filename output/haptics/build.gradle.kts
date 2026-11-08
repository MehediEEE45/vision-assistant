plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.output.haptics"
}

dependencies {
    implementation(project(":core"))
    implementation(project(":protocol"))
    implementation(project(":spine:output-arbiter"))
}
