package main

import (
	"fmt"
	"os"

	"example.com/aos-pkg/internal/model"
	"example.com/aos-pkg/internal/store"
)

const (
	cpmSubdir  = ".cpmctl"
	cpmDBFile  = "cpmdb.json"
	cpmVersion = "0.0.3"
)

func usage() {
	fmt.Println("cpmctl - Container package manager (v" + cpmVersion + ")")
	fmt.Println()
	fmt.Println("Usage:")
	fmt.Println("  cpmctl init")
	fmt.Println("  cpmctl add <name> <version> <image> <summary>")
	fmt.Println("  cpmctl list")
	fmt.Println("  cpmctl info <name>")
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(1)
	}

	cmd := os.Args[1]

	dbPath, err := store.DefaultPath(cpmSubdir, cpmDBFile)
	if err != nil {
		fmt.Println("error: cannot determine db path:", err)
		os.Exit(1)
	}
	st := store.NewStore[model.CpmPackage](dbPath)

	switch cmd {
	case "init":
		if err := st.Init(); err != nil {
			fmt.Println("error: init db:", err)
			os.Exit(1)
		}
		fmt.Println("cpmctl: initialized db at", dbPath)

	case "add":
		if len(os.Args) < 6 {
			fmt.Println("error: missing arguments for add")
			fmt.Println("usage: cpmctl add <name> <version> <image> <summary>")
			os.Exit(1)
		}
		name := os.Args[2]
		version := os.Args[3]
		image := os.Args[4]
		summary := os.Args[5]

		if err := st.Load(); err != nil {
			fmt.Println("error: load db:", err)
			os.Exit(1)
		}

		pkg := model.CpmPackage{
			Name:    name,
			Version: version,
			Image:   image,
			Summary: summary,
		}
		if err := st.Add(pkg); err != nil {
			fmt.Println("error:", err)
			os.Exit(1)
		}
		fmt.Println("cpmctl: added package", name)

	case "list":
		if err := st.Load(); err != nil {
			fmt.Println("error: load db:", err)
			os.Exit(1)
		}
		pkgs := st.List()
		if len(pkgs) == 0 {
			fmt.Println("no CPM packages in local DB")
			return
		}
		fmt.Println("Installed CPM packages:")
		for _, p := range pkgs {
			fmt.Printf("  %s %s\n    image: %s\n    desc : %s\n", p.Name, p.Version, p.Image, p.Summary)
		}

	case "info":
		if len(os.Args) < 3 {
			fmt.Println("error: missing package name")
			fmt.Println("usage: cpmctl info <name>")
			os.Exit(1)
		}
		name := os.Args[2]

		if err := st.Load(); err != nil {
			fmt.Println("error: load db:", err)
			os.Exit(1)
		}

		p, ok := st.Find(name)
		if !ok {
			fmt.Println("package not found:", name)
			os.Exit(1)
		}
		fmt.Println("Name   :", p.Name)
		fmt.Println("Version:", p.Version)
		fmt.Println("Image  :", p.Image)
		fmt.Println("Summary:", p.Summary)
		fmt.Println("DB Path:", dbPath)

	default:
		fmt.Println("error: unknown command:", cmd)
		usage()
		os.Exit(1)
	}
}
