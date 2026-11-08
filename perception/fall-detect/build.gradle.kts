plugins {
    id("vision.kotlin.jvm")
}

dependencies {
    api(project(":core"))
    implementation(project(":protocol"))
}
