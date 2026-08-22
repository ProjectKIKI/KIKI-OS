package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"example.com/aos-pkg/internal/bosrecipe"
	"example.com/aos-pkg/internal/buildsystem"
)

func main() {
	recipeBase64 := flag.String("recipe-base64", "", "base64url-encoded immutable BOS recipe")
	output := flag.String("output", "", "output .bos path")
	workspace := flag.String("workspace-root", "/workspace", "ephemeral workspace root")
	packager := flag.String("packager", "/usr/local/bin/bosbuild", "trusted bosbuild executable")
	dependencyResolver := flag.String("dependency-resolver", "/usr/local/bin/kiki-bos-deps", "trusted build dependency resolver")
	flag.Parse()
	data, err := base64.RawURLEncoding.DecodeString(*recipeBase64)
	if err != nil {
		fail("decode recipe: %v", err)
	}
	var recipe buildsystem.BOSRecipe
	if err := json.Unmarshal(data, &recipe); err != nil {
		fail("parse recipe: %v", err)
	}
	if err := bosrecipe.Build(context.Background(), bosrecipe.Options{Recipe: recipe, Output: *output, WorkspaceRoot: *workspace, PackagerPath: *packager, DependencyPath: *dependencyResolver}); err != nil {
		fail("build recipe: %v", err)
	}
}

func fail(format string, args ...any) {
	_, _ = fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}
