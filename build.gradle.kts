// The Android and Kotlin plugins reach subprojects through buildSrc's
// convention plugins (vision.android.library / vision.kotlin.jvm), so there is
// deliberately no `plugins { ... apply false }` block here. Declaring versions
// in both places makes Gradle refuse to resolve either.

// ---------------------------------------------------------------------------
// Architectural rule #1, enforced.
//
// No feature module may reach an output module. Features propose announcements
// to :spine:output-arbiter and the arbiter alone decides what is heard. If a
// feature could import :output:tts it eventually will, under deadline, and the
// priority ladder stops being true.
//
// Run: ./gradlew checkArchitecture
// ---------------------------------------------------------------------------

val layerOf: (String) -> String = { path ->
    when {
        path == ":app" -> "app"
        path == ":core" -> "core"
        path == ":protocol" -> "protocol"
        path.startsWith(":spine:") -> "spine"
        path.startsWith(":input:") -> "input"
        path.startsWith(":perception:") -> "perception"
        path.startsWith(":output:") -> "output"
        path.startsWith(":feature:") -> "feature"
        else -> "unknown"
    }
}

val allowedTargets: Map<String, Set<String>> = mapOf(
    "core" to emptySet(),
    "protocol" to setOf("core"),
    "spine" to setOf("core"),
    "input" to setOf("core", "protocol"),
    "perception" to setOf("core", "protocol", "input"),
    "output" to setOf("core", "protocol", "spine"),
    "feature" to setOf("core", "spine", "input", "perception"),
    "app" to setOf("core", "protocol", "spine", "input", "perception", "output", "feature"),
)

val declaredEdges = mutableListOf<String>()

gradle.projectsEvaluated {
    subprojects.forEach { project ->
        val consumerPath = project.path
        project.configurations
            .filter { it.name in setOf("implementation", "api", "compileOnly", "runtimeOnly") }
            .forEach { configuration ->
                configuration.dependencies
                    .filterIsInstance<ProjectDependency>()
                    .forEach { dependency ->
                        @Suppress("DEPRECATION")
                        declaredEdges += "$consumerPath -> ${dependency.dependencyProject.path}"
                    }
            }
    }
}

tasks.register("checkArchitecture") {
    group = "verification"
    description = "Fails if any module dependency crosses a forbidden layer boundary."

    val edges = declaredEdges
    val layers = layerOf
    val allowed = allowedTargets

    doLast {
        val violations = edges.mapNotNull { edge ->
            val (from, to) = edge.split(" -> ")
            val fromLayer = layers(from)
            val toLayer = layers(to)
            if (fromLayer == toLayer) return@mapNotNull null
            val permitted = allowed[fromLayer] ?: emptySet()
            if (toLayer in permitted) null
            else "  $from  ($fromLayer)  ->  $to  ($toLayer)"
        }

        if (violations.isNotEmpty()) {
            throw GradleException(
                buildString {
                    appendLine("Forbidden module dependencies (${violations.size}):")
                    violations.forEach { appendLine(it) }
                    appendLine()
                    appendLine("A feature must not depend on an output module. Submit an Announcement")
                    appendLine("to :spine:output-arbiter instead. See docs/architecture.md.")
                }
            )
        }

        logger.lifecycle("checkArchitecture: ${edges.size} module edges, all within policy.")
    }
}

// ---------------------------------------------------------------------------
// Safety-language policy, enforced.
//
// This app reports observations; it never certifies that an action is safe.
// The distinction is easy to lose under deadline pressure, so it fails the
// build rather than depending on someone catching it in review.
// ---------------------------------------------------------------------------

tasks.register("checkSafetyLanguage") {
    group = "verification"
    description = "Fails if any string resource promises the user that something is safe."

    val phraseFile = layout.projectDirectory.file("spine/safety-policy/src/main/resources/banned-phrases.txt")
    val stringFiles = fileTree(rootDir) {
        include("**/src/main/res/values*/strings.xml")
        exclude("**/build/**")
    }

    inputs.file(phraseFile)
    inputs.files(stringFiles)

    doLast {
        val banned = phraseFile.asFile.readLines()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .map { it.lowercase() }

        // Only the value of each <string> element. Comments are skipped on
        // purpose: the files document the banned phrasing alongside the
        // approved alternative, and that documentation is the point.
        val comment = Regex("<!--.*?-->", RegexOption.DOT_MATCHES_ALL)
        val stringElement = Regex(
            "<string[^>]*name=\"([^\"]+)\"[^>]*>(.*?)</string>",
            RegexOption.DOT_MATCHES_ALL,
        )

        val violations = mutableListOf<String>()
        stringFiles.forEach { file ->
            val body = file.readText().replace(comment, "")
            stringElement.findAll(body).forEach { match ->
                val name = match.groupValues[1]
                val value = match.groupValues[2].lowercase()
                banned.filter { value.contains(it) }.forEach { phrase ->
                    violations += "  ${file.relativeTo(rootDir)}  @string/$name  contains \"$phrase\""
                }
            }
        }

        if (violations.isNotEmpty()) {
            throw GradleException(
                buildString {
                    appendLine("Banned safety phrases in string resources (${violations.size}):")
                    violations.forEach { appendLine(it) }
                    appendLine()
                    appendLine("Report what was observed, never that it is safe to act.")
                    appendLine("  say:  \"Traffic light detected ahead.\"")
                    appendLine("  not:  \"It is safe to cross.\"")
                }
            )
        }

        logger.lifecycle("checkSafetyLanguage: ${stringFiles.files.size} resource files clean.")
    }
}

tasks.register("check") {
    group = "verification"
    dependsOn("checkArchitecture", "checkSafetyLanguage")
}

tasks.register("clean", Delete::class) {
    delete(rootProject.layout.buildDirectory)
}
