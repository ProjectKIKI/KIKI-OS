package main

import (
	"archive/tar"
	"compress/gzip"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

const appVersion = "0.0.3"

func usage() {
	fmt.Println("bosbuild - AOS BOS package builder (v" + appVersion + ")")
	fmt.Println()
	fmt.Println("Usage:")
	fmt.Println("  bosbuild -C <workdir> -o <output.bos>")
	fmt.Println()
	fmt.Println("Options:")
	fmt.Println("  -C   Work directory containing manifest.yaml, rootfs/, and optional scripts/")
	fmt.Println("  -o   Output BOS package file (*.bos)")
}

func main() {
	workdir := flag.String("C", "", "work directory containing manifest.yaml, rootfs/, and optional scripts/")
	output := flag.String("o", "", "output BOS package file (*.bos)")
	flag.Usage = usage
	flag.Parse()

	if *workdir == "" || *output == "" {
		usage()
		os.Exit(1)
	}

	if err := buildBos(*workdir, *output); err != nil {
		fmt.Println("error:", err)
		os.Exit(1)
	}

	fmt.Println("bosbuild: created", *output)
}

func buildBos(workdir, output string) error {
	workdirAbs, err := filepath.Abs(workdir)
	if err != nil {
		return fmt.Errorf("resolve workdir: %w", err)
	}
	outputAbs, err := filepath.Abs(output)
	if err != nil {
		return fmt.Errorf("resolve output: %w", err)
	}

	manifestPath := filepath.Join(workdirAbs, "manifest.yaml")
	if info, err := os.Stat(manifestPath); err != nil {
		return fmt.Errorf("manifest.yaml not found in workdir: %w", err)
	} else if info.IsDir() {
		return fmt.Errorf("manifest.yaml is a directory")
	}

	outputDir := filepath.Dir(outputAbs)
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return fmt.Errorf("create output directory: %w", err)
	}

	tmpFile, err := os.CreateTemp(outputDir, ".bosbuild-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary output: %w", err)
	}
	tmpPath := tmpFile.Name()
	tmpAbs, err := filepath.Abs(tmpPath)
	if err != nil {
		tmpFile.Close()
		os.Remove(tmpPath)
		return fmt.Errorf("resolve temporary output: %w", err)
	}

	keepTemp := false
	defer func() {
		if !keepTemp {
			os.Remove(tmpPath)
		}
	}()

	gz := gzip.NewWriter(tmpFile)
	tw := tar.NewWriter(gz)

	if err := filepath.WalkDir(workdirAbs, func(path string, d os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}

		pathAbs, err := filepath.Abs(path)
		if err != nil {
			return err
		}
		if samePath(pathAbs, outputAbs) || samePath(pathAbs, tmpAbs) {
			return nil
		}

		rel, err := filepath.Rel(workdirAbs, pathAbs)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}

		return addPathToTar(tw, workdirAbs, pathAbs, d)
	}); err != nil {
		closeWriters(tw, gz, tmpFile)
		return fmt.Errorf("walk workdir: %w", err)
	}

	if err := tw.Close(); err != nil {
		gz.Close()
		tmpFile.Close()
		return fmt.Errorf("close tar writer: %w", err)
	}
	if err := gz.Close(); err != nil {
		tmpFile.Close()
		return fmt.Errorf("close gzip writer: %w", err)
	}
	if err := tmpFile.Close(); err != nil {
		return fmt.Errorf("close output: %w", err)
	}

	if err := os.Remove(outputAbs); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("replace existing output: %w", err)
	}
	if err := os.Rename(tmpPath, outputAbs); err != nil {
		return fmt.Errorf("move output into place: %w", err)
	}
	keepTemp = true

	return nil
}

func addPathToTar(tw *tar.Writer, workdir, path string, d os.DirEntry) error {
	info, err := d.Info()
	if err != nil {
		return err
	}

	var linkTarget string
	if info.Mode()&os.ModeSymlink != 0 {
		linkTarget, err = os.Readlink(path)
		if err != nil {
			return err
		}
	} else if !info.Mode().IsRegular() && !info.IsDir() {
		return nil
	}

	hdr, err := tar.FileInfoHeader(info, linkTarget)
	if err != nil {
		return err
	}
	rel, err := filepath.Rel(workdir, path)
	if err != nil {
		return err
	}
	hdr.Name = filepath.ToSlash(rel)

	if err := tw.WriteHeader(hdr); err != nil {
		return err
	}
	if !info.Mode().IsRegular() {
		return nil
	}

	f, err := os.Open(path)
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(tw, f)
	closeErr := f.Close()
	if copyErr != nil {
		return copyErr
	}
	return closeErr
}

func samePath(a, b string) bool {
	rel, err := filepath.Rel(a, b)
	return err == nil && rel == "."
}

func closeWriters(tw *tar.Writer, gz *gzip.Writer, f *os.File) {
	_ = tw.Close()
	_ = gz.Close()
	_ = f.Close()
}
